import sys
from pathlib import Path


sys.path.append(str(Path(__file__).resolve().parent.parent))



from common.llm_client import LLMClient, count_tokens
from common.site_checker import check_site, member_names_from_content
from common.embed_images import embed_images


from rag import create_rag, search



_MAX_STEPS : int = 25



def search_style_guide(query : str) -> None:
    pass


def read_profiles() -> None:
    pass


def write_site(html : str) -> None:
    pass


def finish(summary : str) -> None:
    pass


def loop() -> None:
    pass


def main() -> None:
    create_rag()
    search("UPB Web Design Board", 5)

    for _ in range(_MAX_STEPS):
        loop()

    ## Nice error message for stopping



if "__main__" == __name__:
    main()
