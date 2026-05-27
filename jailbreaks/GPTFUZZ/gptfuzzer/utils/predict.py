from transformers import RobertaForSequenceClassification, RobertaTokenizer
import torch


class Predictor:
    def __init__(self, path):
        self.path = path

    def predict(self, sequences):
        raise NotImplementedError("Predictor must implement predict method.")


class RoBERTaPredictor(Predictor):
    def __init__(self, path, device='cuda', batch_size=8):
        super().__init__(path)
        self.device = device
        self.batch_size = max(1, int(batch_size))
        self.model = RobertaForSequenceClassification.from_pretrained(self.path)
        if isinstance(self.device, str) and self.device.startswith('cuda'):
            self.model = self.model.half()
        self.model = self.model.to(self.device)
        self.tokenizer = RobertaTokenizer.from_pretrained(self.path)
        self.model.eval()

    def predict(self, sequences):
        predicted_classes = []

        for i in range(0, len(sequences), self.batch_size):
            batch = sequences[i:i + self.batch_size]
            inputs = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt"
            ).to(self.device)

            with torch.no_grad():
                outputs = self.model(**inputs)

            predictions = torch.nn.functional.softmax(outputs.logits, dim=-1)
            _, batch_classes = torch.max(predictions, dim=1)
            predicted_classes.extend(batch_classes.cpu().tolist())

            if isinstance(self.device, str) and self.device.startswith('cuda'):
                torch.cuda.empty_cache()

        return predicted_classes
