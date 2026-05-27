import logging
import time
import csv

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .mutator import Mutator, MutatePolicy
    from .selection import SelectPolicy

from gptfuzzer.llm import LLM, LocalLLM
from gptfuzzer.utils.template import synthesis_message
from gptfuzzer.utils.predict import Predictor
import warnings


class PromptNode:
    def __init__(self,
                 fuzzer: 'GPTFuzzer',
                 prompt: str,
                 response: str = None,
                 results: 'list[int]' = None,
                 parent: 'PromptNode' = None,
                 mutator: 'Mutator' = None):
        self.fuzzer: 'GPTFuzzer' = fuzzer
        self.prompt: str = prompt
        self.response: str = response
        self.results: 'list[int]' = results
        self.visited_num = 0

        self.parent: 'PromptNode' = parent
        self.mutator: 'Mutator' = mutator
        self.child: 'list[PromptNode]' = []
        self.level: int = 0 if parent is None else parent.level + 1

        self._index: int = None

    @property
    def index(self):
        return self._index

    @index.setter
    def index(self, index: int):
        self._index = index
        if self.parent is not None:
            self.parent.child.append(self)

    @property
    def num_jailbreak(self):
        return sum(self.results)

    @property
    def num_reject(self):
        return len(self.results) - sum(self.results)

    @property
    def num_query(self):
        return len(self.results)


class GPTFuzzer:
    def __init__(self,
                 questions: 'list[str]',
                 target: 'LLM',
                 predictor: 'Predictor',
                 initial_seed: 'list[str]',
                 mutate_policy: 'MutatePolicy',
                 select_policy: 'SelectPolicy',
                 max_query: int = -1,
                 max_jailbreak: int = -1,
                 max_reject: int = -1,
                 max_iteration: int = -1,
                 energy: int = 1,
                 result_file: str = None,
                 eval_log_file: str = None,
                 generate_in_batch: bool = False,
                 ):

        self.questions: 'list[str]' = questions
        self.target: LLM = target
        self.predictor = predictor
        self.prompt_nodes: 'list[PromptNode]' = [
            PromptNode(self, prompt) for prompt in initial_seed
        ]
        self.initial_prompts_nodes = self.prompt_nodes.copy()

        for i, prompt_node in enumerate(self.prompt_nodes):
            prompt_node.index = i

        self.mutate_policy = mutate_policy
        self.select_policy = select_policy

        self.current_query: int = 0
        self.current_jailbreak: int = 0
        self.current_reject: int = 0
        self.current_iteration: int = 0

        self.max_query: int = max_query
        self.max_jailbreak: int = max_jailbreak
        self.max_reject: int = max_reject
        self.max_iteration: int = max_iteration

        self.energy: int = energy
        if result_file is None:
            result_file = f'results-{time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())}.csv'

        self.raw_fp = open(result_file, 'w', buffering=1)
        self.writter = csv.writer(self.raw_fp, delimiter='|')
        self.writter.writerow(
            ['index', 'prompt', 'response', 'parent', 'results'])

        self.eval_log_fp = None
        self.eval_writter = None
        self.eval_query_id = 0
        self.template_eval_id = 0
        if eval_log_file is not None:
            self.eval_log_fp = open(eval_log_file, 'w', buffering=1)
            self.eval_writter = csv.writer(self.eval_log_fp, delimiter='|')
            self.eval_writter.writerow([
                'query_id',
                'template_eval_id',
                'iteration',
                'question_idx',
                'question',
                'prompt',
                'result',
                'response',
                'parent',
            ])

        self.generate_in_batch = False
        if len(self.questions) > 0 and generate_in_batch is True:
            self.generate_in_batch = True
            if isinstance(self.target, LocalLLM):
                warnings.warn("IMPORTANT! Hugging face inference with batch generation has the problem of consistency due to pad tokens. We do not suggest doing so and you may experience (1) degraded output quality due to long padding tokens, (2) inconsistent responses due to different number of padding tokens during reproduction. You should turn off generate_in_batch or use vllm batch inference.")
        self.run_start_time = None
        self.setup()

    def setup(self):
        self.mutate_policy.fuzzer = self
        self.select_policy.fuzzer = self
        logging.basicConfig(
            level=logging.INFO, format='%(asctime)s %(message)s', datefmt='[%H:%M:%S]')

    def is_stop(self):
        checks = [
            ('max_query', 'current_query'),
            ('max_jailbreak', 'current_jailbreak'),
            ('max_reject', 'current_reject'),
            ('max_iteration', 'current_iteration'),
        ]
        return any(getattr(self, max_attr) != -1 and getattr(self, curr_attr) >= getattr(self, max_attr) for max_attr, curr_attr in checks)

    def run(self):
        logging.info("Fuzzing started!")
        self.run_start_time = time.time()
        try:
            while not self.is_stop():
                seed = self.select_policy.select()
                mutated_results = self.mutate_policy.mutate_single(seed)
                self.evaluate(mutated_results)
                self.update(mutated_results)
                self.log()
        except KeyboardInterrupt:
            logging.info("Fuzzing interrupted by user!")

        logging.info("Fuzzing finished!")
        self.raw_fp.close()
        if self.eval_log_fp is not None:
            self.eval_log_fp.close()

    def evaluate(self, prompt_nodes: 'list[PromptNode]'):
        total_templates = len(prompt_nodes)
        total_questions = len(self.questions)
        checkpoint_every = 10

        for template_idx, prompt_node in enumerate(prompt_nodes, start=1):
            logging.info(
                f"Iteration {self.current_iteration + 1}: evaluating template {template_idx}/{total_templates} "
                f"on {total_questions} questions"
            )
            responses = []
            messages = []
            valid_prompt = True
            for question_idx, question in enumerate(self.questions, start=1):
                message = synthesis_message(question, prompt_node.prompt)
                if message is None:  # The prompt is not valid
                    prompt_node.response = []
                    prompt_node.results = []
                    valid_prompt = False
                    break
                if not self.generate_in_batch:
                    response = self.target.generate(message)
                    responses.append(response[0] if isinstance(
                        response, list) else response)
                    if question_idx % checkpoint_every == 0 or question_idx == total_questions:
                        logging.info(
                            f"Iteration {self.current_iteration + 1}: template {template_idx}/{total_templates}, "
                            f"processed questions {question_idx}/{total_questions}"
                        )
                else:
                    messages.append(message)
                    if question_idx % checkpoint_every == 0 or question_idx == total_questions:
                        logging.info(
                            f"Iteration {self.current_iteration + 1}: template {template_idx}/{total_templates}, "
                            f"prepared batched prompts {question_idx}/{total_questions}"
                        )

            if not valid_prompt:
                continue

            if self.generate_in_batch:
                logging.info(
                    f"Iteration {self.current_iteration + 1}: template {template_idx}/{total_templates}, "
                    f"running batched generation for {len(messages)} prompts"
                )
                responses = self.target.generate_batch(messages)
            prompt_node.response = responses
            prompt_node.results = self.predictor.predict(responses)
            logging.info(
                f"Iteration {self.current_iteration + 1}: template {template_idx}/{total_templates}, "
                f"judge completed ({sum(prompt_node.results)}/{len(prompt_node.results)} jailbreaks)"
            )

            if self.eval_writter is not None:
                self.template_eval_id += 1
                parent_index = prompt_node.parent.index if prompt_node.parent is not None else -1
                iteration = self.current_iteration + 1
                for question_idx, (question, response, result) in enumerate(zip(self.questions, responses, prompt_node.results)):
                    self.eval_query_id += 1
                    self.eval_writter.writerow([
                        self.eval_query_id,
                        self.template_eval_id,
                        iteration,
                        question_idx,
                        question,
                        prompt_node.prompt,
                        int(result),
                        response,
                        parent_index,
                    ])

    def update(self, prompt_nodes: 'list[PromptNode]'):
        self.current_iteration += 1

        for prompt_node in prompt_nodes:
            if prompt_node.num_jailbreak > 0:
                prompt_node.index = len(self.prompt_nodes)
                self.prompt_nodes.append(prompt_node)
                self.writter.writerow([prompt_node.index, prompt_node.prompt,
                                       prompt_node.response, prompt_node.parent.index, prompt_node.results])

            self.current_jailbreak += prompt_node.num_jailbreak
            self.current_query += prompt_node.num_query
            self.current_reject += prompt_node.num_reject

        self.select_policy.update(prompt_nodes)

    def log(self):
        if self.max_query is not None and self.max_query > 0 and self.run_start_time is not None:
            elapsed = max(time.time() - self.run_start_time, 1e-6)
            qps = self.current_query / elapsed
            remaining_queries = max(self.max_query - self.current_query, 0)
            eta_seconds = int(remaining_queries / qps) if qps > 0 else -1

            if eta_seconds >= 0:
                eta_h = eta_seconds // 3600
                eta_m = (eta_seconds % 3600) // 60
                eta_s = eta_seconds % 60
                eta_text = f"{eta_h:02d}:{eta_m:02d}:{eta_s:02d}"
            else:
                eta_text = "unknown"

            progress = min(self.current_query / self.max_query, 1.0)
            bar_width = 20
            filled = int(progress * bar_width)
            bar = "#" * filled + "-" * (bar_width - filled)

            logging.info(
                f"Iteration {self.current_iteration}: {self.current_jailbreak} jailbreaks, "
                f"{self.current_reject} rejects, {self.current_query}/{self.max_query} queries | "
                f"[{bar}] {progress * 100:5.1f}% | {qps:.2f} q/s | ETA {eta_text}"
            )
        else:
            logging.info(
                f"Iteration {self.current_iteration}: {self.current_jailbreak} jailbreaks, {self.current_reject} rejects, {self.current_query} queries")
