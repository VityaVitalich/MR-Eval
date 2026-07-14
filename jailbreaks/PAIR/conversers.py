from common import get_api_key, conv_template, extract_json
from language_models import APILiteLLM, LocalvLLM, LocalHF, LocalVLLMServerLLM
from config import FASTCHAT_TEMPLATE_NAMES, Model
from loggers import logger


def load_attack_and_target_models(args):
    # Two backends supported: a single backend for both (legacy `--local-backend`),
    # or per-role backends (`--attack-backend` / `--target-backend`) so the
    # attacker can run as a separate `vllm serve` (GPUs 0,1) while the target
    # uses in-process LocalvLLM (GPUs 2,3) — the standard PAIR-on-4xH100 layout.
    legacy = getattr(args, "local_backend", "hf")
    attack_backend = getattr(args, "attack_backend", None) or legacy
    target_backend = getattr(args, "target_backend", None) or legacy

    attackLM = AttackLM(model_name = args.attack_model,
                        max_n_tokens = args.attack_max_n_tokens,
                        max_n_attack_attempts = args.max_n_attack_attempts,
                        category = args.category,
                        evaluate_locally = args.evaluate_locally,
                        local_backend = attack_backend,
                        backend_kwargs = _attacker_backend_kwargs(args, attack_backend),
                        )

    targetLM = TargetLM(model_name = args.target_model,
                        category = args.category,
                        max_n_tokens = args.target_max_n_tokens,
                        evaluate_locally = args.evaluate_locally,
                        phase = args.jailbreakbench_phase,
                        use_jailbreakbench = getattr(args, "use_jailbreakbench", True),
                        local_backend = target_backend,
                        )

    return attackLM, targetLM


def _attacker_backend_kwargs(args, backend: str) -> dict:
    """Build the backend-specific kwargs for the attacker (only `server` uses any)."""
    if backend != "server":
        return {}
    return {
        "endpoint":    getattr(args, "attack_endpoint", "http://localhost:8000/v1"),
        "served_name": getattr(args, "attack_served_name", "pair-attacker"),
    }


_OPENROUTER_MODEL_NAMES = {"gpt-3.5-turbo-openrouter", "gpt-4o-openrouter"}

def load_indiv_model(
    model_name, local=False, use_jailbreakbench=True, local_backend: str = "hf",
    backend_kwargs: dict | None = None,
):
    backend_kwargs = backend_kwargs or {}
    # OpenRouter-routed models are always API-based; ignore --evaluate-locally for them.
    if str(model_name) in _OPENROUTER_MODEL_NAMES:
        return APILiteLLM(model_name)
    if use_jailbreakbench and not local:
        # Together-hosted target via JailbreakBench's LiteLLM wrapper.
        from jailbreakbench import LLMLiteLLM
        api_key = get_api_key(Model(model_name))
        lm = LLMLiteLLM(model_name= model_name, api_key = api_key)
    else:
        # Local path (attacker or target with --evaluate-locally), or non-JBB API.
        if local:
            if local_backend == "vllm":
                lm = LocalvLLM(model_name)
            elif local_backend == "hf":
                lm = LocalHF(model_name)
            elif local_backend == "server":
                # Remote vLLM server (attacker). `model_name` is irrelevant — the
                # served-name + endpoint come from backend_kwargs.
                lm = LocalVLLMServerLLM(
                    served_name=backend_kwargs.get("served_name", "pair-attacker"),
                    endpoint=backend_kwargs.get("endpoint", "http://localhost:8000/v1"),
                )
            else:
                raise ValueError(f"Unknown --local-backend: {local_backend!r} "
                                 f"(expected hf | vllm | server)")
        else:
            lm = APILiteLLM(model_name)
    return lm

class AttackLM():
    """
        Base class for attacker language models.

        Generates attacks for conversations using a language model. The self.model attribute contains the underlying generation model.
    """
    def __init__(self,
                model_name: str,
                max_n_tokens: int,
                max_n_attack_attempts: int,
                category: str,
                evaluate_locally: bool,
                local_backend: str = "hf",
                backend_kwargs: dict | None = None):

        # The `server` backend is built around any HF model — no enum entry
        # required. Try the enum lookup; on failure, keep the raw string.
        try:
            self.model_name = Model(model_name)
        except ValueError:
            self.model_name = model_name
        self.max_n_tokens = max_n_tokens
        self.max_n_attack_attempts = max_n_attack_attempts

        from config import ATTACK_TEMP, ATTACK_TOP_P
        self.temperature = ATTACK_TEMP
        self.top_p = ATTACK_TOP_P

        self.category = category
        self.evaluate_locally = evaluate_locally
        self.model = load_indiv_model(model_name,
                                      local = evaluate_locally,
                                      use_jailbreakbench=False, # Cannot use JBB as attacker
                                      local_backend=local_backend,
                                      backend_kwargs=backend_kwargs,
                                      )
        self.initialize_output = self.model.use_open_source_model
        # Template only used by `preprocess_conversation` for open-source models
        # (and downstream by `conv_template(template)` callers). For the server
        # backend the server applies its own chat template, so we never hit
        # this lookup — but provide a safe default for any future use.
        if isinstance(self.model_name, Model) and self.model_name in FASTCHAT_TEMPLATE_NAMES:
            self.template = FASTCHAT_TEMPLATE_NAMES[self.model_name]
        else:
            from language_models import _guess_fastchat_template
            self.template = _guess_fastchat_template(str(self.model_name))

    def preprocess_conversation(self, convs_list: list, prompts_list: list[str]):
        # For open source models, we can seed the generation with proper JSON
        init_message = ""
        if self.initialize_output:
            
            # Initalize the attack model's generated output to match format
            if len(convs_list[0].messages) == 0:# If is first message, don't need improvement
                init_message = '{"improvement": "","prompt": "'
            else:
                init_message = '{"improvement": "'
        for conv, prompt in zip(convs_list, prompts_list):
            conv.append_message(conv.roles[0], prompt)
            if self.initialize_output:
                conv.append_message(conv.roles[1], init_message)
        openai_convs_list = [conv.to_openai_api_messages() for conv in convs_list]
        return openai_convs_list, init_message
        
    def _generate_attack(self, openai_conv_list: list[list[dict]], init_message: str):
        batchsize = len(openai_conv_list)
        indices_to_regenerate = list(range(batchsize))
        valid_outputs = [None] * batchsize
        new_adv_prompts = [None] * batchsize

        # Logging hooks: per-stream, the inputs we sent + the FINAL raw attacker
        # output that produced the parsed JSON, plus the # of attempts used.
        # `main._log_iteration` reads these via `attackLM.last_*`.
        self.last_inputs = list(openai_conv_list)
        self.last_raw_outputs: list[str | None] = [None] * batchsize
        self.last_attempts_used: list[int] = [0] * batchsize

        # Continuously generate outputs until all are valid or max_n_attack_attempts is reached
        for attempt in range(self.max_n_attack_attempts):
            # Subset conversations based on indices to regenerate
            convs_subset = [openai_conv_list[i] for i in indices_to_regenerate]
            # Generate outputs — no `extra_eos_tokens=["}"]` clip: with
            # thinking-mode attackers (Qwen3/DeepSeek-R1/…) the reasoning text
            # contains stray `}` chars that truncate generation mid-think. We
            # let the model emit `<think>…</think>{full JSON}` and use
            # extract_json's <think>-strip + LAST-brace pair logic to parse.
            # The init_message-prefill path (open-source backends) still
            # benefits from a self-closing JSON since the model continues from
            # `{"improvement": ...` and emits the closing `}` itself.
            outputs_list = self.model.batched_generate(convs_subset,
                                                        max_n_tokens = self.max_n_tokens,
                                                        temperature = self.temperature,
                                                        top_p = self.top_p,
                                                    )

            # Check for valid outputs and update the list
            new_indices_to_regenerate = []
            for i, full_output in enumerate(outputs_list):
                orig_index = indices_to_regenerate[i]
                if full_output is None:
                    # API returned no content (e.g., safety-blocked refusal). Treat as invalid; will retry.
                    new_indices_to_regenerate.append(orig_index)
                    continue
                # Prepend the prefill seed (open-source path only; "" for server)
                # so extract_json sees a complete JSON object. The model is now
                # expected to close its own `}` since we dropped the stop clip.
                full_output = init_message + full_output
                attack_dict, json_str = extract_json(full_output)
                if attack_dict is not None:
                    valid_outputs[orig_index] = attack_dict
                    new_adv_prompts[orig_index] = json_str
                    self.last_raw_outputs[orig_index] = full_output
                    self.last_attempts_used[orig_index] = attempt + 1
                else:
                    new_indices_to_regenerate.append(orig_index)

            # Update indices to regenerate for the next iteration
            indices_to_regenerate = new_indices_to_regenerate
            # If all outputs are valid, break
            if not indices_to_regenerate:
                break

        n_failed = sum(1 for o in valid_outputs if o is None)
        if n_failed:
            # Per-stream tolerance: with goal-batched search (M*S streams),
            # losing one stream to JSON-parse variance shouldn't kill the
            # whole chunk's iteration. Stub out failed streams with an empty
            # `improvement` + a fallback prompt (the bare goal text). The main
            # loop logs them with attacker_json_ok=False; the outer rejudge
            # scores them like any other attempt.
            logger.warning(
                f"Attacker failed to produce valid JSON on {n_failed}/{len(valid_outputs)} "
                f"streams after {self.max_n_attack_attempts} retries; substituting "
                f"fallback prompts so the chunk can continue.")
            for i, out in enumerate(valid_outputs):
                if out is None:
                    valid_outputs[i] = {
                        "improvement": "",
                        "prompt": "[FALLBACK: attacker failed to emit JSON; using empty prompt]",
                    }
                    new_adv_prompts[i] = '{"improvement": "", "prompt": "[FALLBACK: attacker failed to emit JSON; using empty prompt]"}'
                    # Mirror the bookkeeping so the wider logger sees this stream:
                    self.last_raw_outputs[i] = self.last_raw_outputs[i] or "<no valid JSON after retries>"
                    self.last_attempts_used[i] = self.max_n_attack_attempts
        return valid_outputs, new_adv_prompts

    def get_attack(self, convs_list, prompts_list):
        """
        Generates responses for a batch of conversations and prompts using a language model. 
        Only valid outputs in proper JSON format are returned. If an output isn't generated 
        successfully after max_n_attack_attempts, it's returned as None.
        
        Parameters:
        - convs_list: List of conversation objects.
        - prompts_list: List of prompts corresponding to each conversation.
        
        Returns:
        - List of generated outputs (dictionaries) or None for failed generations.
        """
        assert len(convs_list) == len(prompts_list), "Mismatch between number of conversations and prompts."
        
        # Convert conv_list to openai format and add the initial message
        processed_convs_list, init_message = self.preprocess_conversation(convs_list, prompts_list)
        valid_outputs, new_adv_prompts = self._generate_attack(processed_convs_list, init_message)

        for jailbreak_prompt, conv in zip(new_adv_prompts, convs_list):
            # For open source models, we can seed the generation with proper JSON and omit the post message
            # We add it back here
            if self.initialize_output:
                jailbreak_prompt += self.model.post_message
            conv.update_last_message(jailbreak_prompt)
        
        return valid_outputs

class TargetLM():
    """
        JailbreakBench class for target language models.
    """
    def __init__(self, 
            model_name: str, 
            category: str,
            max_n_tokens : int,
            phase: str,
            evaluate_locally: bool = False,
            use_jailbreakbench: bool = True,
            local_backend: str = "hf",
            ):
        
        self.model_name = model_name
        self.max_n_tokens = max_n_tokens
        self.phase = phase
        # If we're evaluating locally we cannot use jailbreakbench's Together
        # API wrapper — force the local generate path.
        self.use_jailbreakbench = use_jailbreakbench and not evaluate_locally
        self.evaluate_locally = evaluate_locally

        from config import TARGET_TEMP,  TARGET_TOP_P   
        self.temperature = TARGET_TEMP
        self.top_p = TARGET_TOP_P

        self.model = load_indiv_model(model_name, evaluate_locally, self.use_jailbreakbench, local_backend=local_backend)
        try:
            self.template = FASTCHAT_TEMPLATE_NAMES[Model(model_name)]
        except (ValueError, KeyError):
            # Raw HF path — guess the template from the model name.
            from language_models import _guess_fastchat_template
            self.template = _guess_fastchat_template(model_name)
        self.category = category
        # Render the target prompt with the model's OWN chat template
        # (tokenizer.apply_chat_template), matching every other MR-Eval jailbreak
        # bench (see jailbreaks/common.generate_from_conversations and
        # runner_core._render). The local vLLM / HF backends read this flag in
        # batched_generate; the `server` backend already applies its chat
        # template internally and the JBB API path never touches it. We do NOT
        # use the guessed fastchat template for the target: for unrecognized
        # model names it silently falls back to a "### Human / ### Assistant"
        # transcript scaffold that the target then continues, contaminating the
        # scored response.
        setattr(self.model, "native_chat_template", True)

    def get_response(self, prompts_list):
        if self.use_jailbreakbench:
            llm_response = self.model.query(prompts = prompts_list, 
                                behavior = self.category, 
                                phase = self.phase,
                                max_new_tokens=self.max_n_tokens)
            responses = llm_response.responses
        else:
            # One clean user turn per adversarial prompt. The backend renders it
            # with the model's native chat template (see native_chat_template in
            # __init__), so we intentionally skip the fastchat conv_template that
            # used to inject a system message + role scaffold here.
            full_prompts = [
                [{"role": "user", "content": prompt}] for prompt in prompts_list
            ]

            responses = self.model.batched_generate(full_prompts,
                                                            max_n_tokens = self.max_n_tokens,
                                                            temperature = self.temperature,
                                                            top_p = self.top_p
                                                        )

        return responses