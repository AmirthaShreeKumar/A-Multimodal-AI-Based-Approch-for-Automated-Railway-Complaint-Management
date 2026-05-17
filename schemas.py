from pydantic import BaseModel, Field
from typing import List, Optional

class ComplaintAnalysis(BaseModel):
    category: str = Field(description="Category of the grievance (e.g., Cleanliness, Safety, etc.)")
    department: str = Field(description="Assigned department (e.g., Housekeeping, Engineering, etc.)")
    priority: str = Field(description="Priority level (High, Medium, Low)")
    sentiment: str = Field(description="Sentiment of the complaint (Positive, Neutral, Negative)")
    summary: str = Field(description="A concise summary of the issue")

class ChatResponse(BaseModel):
    response: str = Field(description="The AI's helpful response to the user query")
    suggested_action: Optional[str] = Field(None, description="A suggested next step for the user")

class FaceVerification(BaseModel):
    match: bool = Field(description="Whether the faces in the two images match")
    confidence: str = Field(description="Confidence level (High, Medium, Low)")
    reason: str = Field(description="Brief explanation of the result")
