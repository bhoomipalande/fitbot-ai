import numpy as np
from google import genai

# Comprehensive Gym Knowledge Base (Policies, Pricing Tiers, Rules, Nutrition & FAQs)
DEFAULT_KNOWLEDGE_DOCS = [
    {
        "title": "Membership Tiers & Billing Policy",
        "content": (
            "Membership Plans: Basic Plan (Gym floor + cardio) starts at ₹1,499/month or ₹14,999/year. "
            "Pro Plan (Includes unlimited Yoga, Zumba, Aerobics, and 1 body composition scan/month) is ₹2,499/month. "
            "Elite Plan (Includes 8 personal training sessions/month + sauna access) is ₹5,999/month. "
            "A one-time registration & RFID access card fee of ₹500 applies to new members."
        ),
    },
    {
        "title": "Membership Freeze, Cancellation & Refund Policy",
        "content": (
            "Membership Freeze Policy: Annual and 6-month members can freeze their membership for up to 30 days "
            "for medical reasons or travel at zero extra cost by submitting a request 48 hours in advance. "
            "Refund & Cancellation Policy: Memberships are non-refundable after 7 days of activation. "
            "Within the first 7 days, a full refund minus the ₹500 registration fee is permitted."
        ),
    },
    {
        "title": "Personal Training & Session Cancellation Rules",
        "content": (
            "Personal Training (PT) Sessions: Single PT sessions cost ₹700, 12-session packs cost ₹7,200, "
            "and 24-session packs cost ₹13,200. PT sessions must be booked at least 4 hours in advance. "
            "Rescheduling or cancellation is free if done at least 6 hours before the scheduled slot; "
            "late cancellations within 6 hours count as a completed session."
        ),
    },
    {
        "title": "Gym Floor Etiquette, Safety & Dress Code",
        "content": (
            "Gym Etiquette & Safety: Clean indoor athletic shoes and workout attire are mandatory on the gym floor; "
            "sandals, jeans, and bare feet (outside the Yoga studio) are not permitted. "
            "Members must carry a workout towel, wipe down machines after use, and re-rack all dumbbells and weight plates. "
            "Minimum age for independent gym access is 16 years (ages 14-15 require parental consent and trainer supervision)."
        ),
    },
    {
        "title": "Nutrition, Supplements & Recovery Guidelines",
        "content": (
            "Nutrition & Recovery: For fat loss, aim for a 300-500 kcal daily calorie deficit with 1.8g-2.0g of protein per kg of body weight. "
            "For muscle hypertrophy, aim for a 250-400 kcal surplus with 2.0g-2.2g of protein per kg of body weight. "
            "Hydration target is 3 to 4 liters of water daily. The in-house FitBar serves whey protein shakes, creatine, and electrolyte drinks."
        ),
    },
    {
        "title": "Locker Room, Guest Pass & Parking Facilities",
        "content": (
            "Facilities: Day-use digital lockers are free during workout hours; overnight storage is prohibited and locks are cut at closing time. "
            "Every active member receives 2 free guest passes per month (guests must present a valid government ID at reception). "
            "Free two-wheeler and four-wheeler parking is available in the basement for up to 2 hours per visit."
        ),
    },
]


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    a = np.array(vec_a, dtype=np.float32)
    b = np.array(vec_b, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def embed_texts(client: genai.Client, texts: list[str]) -> list[list[float]]:
    """Generates vector embeddings using Gemini's embedding model with a deterministic fallback."""
    embeddings = []
    for text in texts:
        try:
            res = client.models.embed_content(
                model="gemini-embedding-001",
                contents=text,
            )
            embeddings.append(res.embeddings[0].values)
        except Exception:
            # Fallback lightweight bag-of-words hash vector if embedding API hits rate limit
            vec = [0.0] * 128
            for word in text.lower().split():
                vec[hash(word) % 128] += 1.0
            embeddings.append(vec)
    return embeddings


def retrieve_relevant_context(
    client: genai.Client,
    query: str,
    docs: list[dict],
    doc_embeddings: list[list[float]],
    top_k: int = 3,
) -> list[dict]:
    """Performs semantic vector search over the gym knowledge base and returns top-k chunks."""
    if not docs or not doc_embeddings:
        return []

    query_embedding = embed_texts(client, [query])[0]
    scored = []
    for doc, emb in zip(docs, doc_embeddings):
        score = _cosine_similarity(query_embedding, emb)
        scored.append({
            "title": doc["title"],
            "content": doc["content"],
            "score": round(score, 3),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]