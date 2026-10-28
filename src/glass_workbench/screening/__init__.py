"""First-order glass screens; results are not optimized lens prescriptions."""
from .triplet import TripletSettings, search_triplets
from .telescope import TelescopeSettings, search_telescope

__all__ = ["TripletSettings", "TelescopeSettings", "search_triplets", "search_telescope"]
