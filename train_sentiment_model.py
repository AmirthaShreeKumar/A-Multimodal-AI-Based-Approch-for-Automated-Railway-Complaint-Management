import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
import joblib
import os

def train_and_save_model(dataset_path='sentiment_dataset.csv', model_path='sentiment_model.pkl'):
    if not os.path.exists(dataset_path):
        print(f"Dataset {dataset_path} not found.")
        return False
        
    print(f"Loading dataset from {dataset_path}...")
    df = pd.read_csv(dataset_path)
    
    # Ensure there are no null values
    df = df.dropna(subset=['text', 'sentiment'])
    
    X = df['text']
    y = df['sentiment']
    
    print("Training the Logistic Regression model with TF-IDF features...")
    pipeline = Pipeline([
        ('tfidf', TfidfVectorizer(stop_words='english', max_features=1000, ngram_range=(1, 2))),
        ('clf', LogisticRegression(random_state=42, C=1.0))
    ])
    
    pipeline.fit(X, y)
    print("Training complete.")
    
    print(f"Saving model to {model_path}...")
    joblib.dump(pipeline, model_path)
    print("Model saved successfully.")
    return True

if __name__ == "__main__":
    train_and_save_model()
