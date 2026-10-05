#services/provider_data.py
"""
A module with a dataclass
to standardize all model 
outputs.
"""

#import dataclass
from dataclasses import dataclass


# create a data class with attributes compatible with our output response schema.
@dataclass
class provider_response:
    response: str
    prompt_tokens: int
    completion_tokens: int
    context_tokens: int
    status_code: int
    status: str
    started_generation: bool
    billable: bool
