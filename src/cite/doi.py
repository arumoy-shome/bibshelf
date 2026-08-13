import re


@dataclass
class Doi:
    @staticmethod
    def isvalid(doi: str, type: str):
        pass

    def __init__(self, doi: str, type: str):
        if not isvalid(doi, type):
            raise ValueError("Something is not right about the DOI")
        pass
