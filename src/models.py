from typing import List, Optional
from pydantic import BaseModel, Field


class Recipe(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    servings: Optional[str] = None
    prep_time: Optional[str] = None
    cook_time: Optional[str] = None
    total_time: Optional[str] = None
    ingredients: List[str] = Field(default_factory=list)
    instructions: List[str] = Field(default_factory=list)
    calories: Optional[str] = None
    cuisine: Optional[str] = None
    course: Optional[str] = None
    image_urls: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    source_url: Optional[str] = None
    extraction_method: str = "jsonld"


class FAQItem(BaseModel):
    question: str
    answer: str


class ImagePrompt(BaseModel):
    type: str
    prompt: str
    placement: str
    description: str
    seo_metadata: dict


class ImagePromptBundle(BaseModel):
    prompts: List[ImagePrompt]
