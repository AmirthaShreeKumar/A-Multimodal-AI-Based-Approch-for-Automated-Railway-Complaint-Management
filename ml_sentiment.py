import os
import joblib

_MODEL_CACHE = None
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'sentiment_model.pkl')

def get_sentiment_model():
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        if os.path.exists(MODEL_PATH):
            try:
                _MODEL_CACHE = joblib.load(MODEL_PATH)
            except Exception as e:
                print(f"Failed to load sentiment model: {e}")
                return None
        else:
            return None
    return _MODEL_CACHE

def predict_sentiment(text: str) -> str:
    """
    Predicts the sentiment of a given text using the trained ML model.
    Returns 'Neutral' as a fallback if the model is not loaded or prediction fails.
    """
    if not text or not text.strip():
        return "Neutral"
        
    model = get_sentiment_model()
    if not model:
        # Fallback if model hasn't been trained yet
        return "Neutral"
        
    try:
        prediction = model.predict([text])
        return str(prediction[0])
    except Exception as e:
        print(f"Error during sentiment prediction: {e}")
        return "Neutral"
