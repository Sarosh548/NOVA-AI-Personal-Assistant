from sentence_transformers import SentenceTransformer, util


class EmbeddingService:
    def __init__(self):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

    def create_embedding(self, text: str):
        return self.model.encode(text)

    def similarity(self, text1: str, text2: str) -> float:
        embedding1 = self.create_embedding(text1)
        embedding2 = self.create_embedding(text2)

        score = util.cos_sim(embedding1, embedding2).item()

        return float(score)