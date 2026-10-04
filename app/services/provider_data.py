#services/provider_data.py
"""
A module with a dataclass
to standardize all model 
outputs.
"""

#import dataclass
from dataclasses import dataclass


# create class
@dataclass
class provider_response:
    response: str
    prompt_tokens: int
    completion_tokens: int
    status_code: int
    status: int
