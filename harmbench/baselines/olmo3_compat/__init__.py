"""OLMo-3 (allenai/Olmo-3-*) for transformers < 4.57, which the harmbench image ships (4.54): registers the transformers
v4.57.1 Olmo3 config and model with the Auto classes. configuration_olmo3.py / modeling_olmo3.py are those files verbatim
except for absolute imports and DynamicCache() without config (4.54 has no layered sliding cache; outputs only differ
past the 4096-token window). No-op where transformers already knows olmo3."""
from transformers.models.auto.configuration_auto import CONFIG_MAPPING

if "olmo3" not in CONFIG_MAPPING:
    from transformers import AutoConfig, AutoModelForCausalLM
    from .configuration_olmo3 import Olmo3Config
    from .modeling_olmo3 import Olmo3ForCausalLM, Olmo3Model, Olmo3PreTrainedModel
    # the image's PreTrainedModel (4.54.0.dev0) predates two 4.57 conveniences the vendored classes rely on:
    Olmo3PreTrainedModel.config_class = Olmo3Config  # config class derived from the `config: Olmo3Config` annotation
    Olmo3Model.get_input_embeddings = lambda self: self.embed_tokens  # generic embedding-layer lookup
    Olmo3Model.set_input_embeddings = lambda self, value: setattr(self, "embed_tokens", value)
    Olmo3ForCausalLM.get_output_embeddings = lambda self: self.lm_head
    Olmo3ForCausalLM.set_output_embeddings = lambda self, value: setattr(self, "lm_head", value)
    AutoConfig.register("olmo3", Olmo3Config)
    AutoModelForCausalLM.register(Olmo3Config, Olmo3ForCausalLM)
