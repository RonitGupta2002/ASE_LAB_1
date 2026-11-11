import sys
import os
import json
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Any


sys.path.append(str(Path(__file__).resolve().parent.parent))



from common.llm_client import LLMClient, count_tokens
from common.site_checker import check_site, member_names_from_content
from common.embed_images import embed_images


from rag import create_rag, search, llm_client


_SYSTEM_PROMPT : str = r"""
You are a coding agent that creates a website from the provided profile content.

Respond with exactly one JSON object per step, with this shape:
{"thought": "brief explanation of the next step", "action": "action_name", "args": {}}

Do not wrap the JSON in Markdown fences or include text before it. Use only these actions and argument schemas:
- search_style_guide: {"query": "<specific question>"}
- read_profiles: {}
- write_site: {} followed immediately by a ```html code block containing the complete HTML page.
- finish: {"summary": "<brief completion summary>"}

Exception regarding response only for the action write_site following JSON response is valid:
{"thought": "brief explanation of the next step", "action": "action_name", "args": {}}```html Webpage```

Use search_style_guide to retrieve relevant style guidance before writing the site. Search results are the only style-guide content available to you; do not assume or invent other rules. A search observation contains at most 1,000 tokens of style-guide text, so make focused queries as needed. Do not put style-guide text in your response except where needed in the generated site.

Use read_profiles to obtain the available profile text. Base profile-specific content on those files; do not invent personal details. For images, use placeholders such as {{image:anna.jpg}} with a suitable alt attribute. Never write base64 image data.

Before finishing, submit a complete HTML page with write_site. The host will resolve image placeholders, save the page, and return a checker report. If the report has failures, fix them and submit the page again. Use finish only after the latest checker report passes. If finish is rejected, address the reported failures instead.

The host may return error observations for invalid output or actions. Recover by following the error and sending a valid response. Human feedback may arrive as a new user message after an accepted finish; treat it as a request to revise the site, then write and check the revised page before finishing again.

Do not claim an action succeeded unless its observation confirms it. Keep thoughts brief and focus on the next action.

PROCEDURE:
STEP 1: read_profiles
STEP 2: write_site
If checks fails:
STEP  : search_style_guide
If not:
STEP 3: finish
"""

_SYSTEM_PROMPT_OBJECT : dict[str] = {
    "role"    : "system",
    "content" : _SYSTEM_PROMPT,
}

_RESPONSE_KEYS : set[str] = {"thought", "action", "args"}

_MAX_STEPS : int = 25
_MAX_K     : int = 5



content_dir : Path
output_path : Path

step_number : int = 0


llm_output : str = ""

successful_report : bool = False
task_done : bool = False


llm_request = [
    _SYSTEM_PROMPT_OBJECT
]



def _write_to_llm(content : str) -> None:
    global llm_output
    global llm_request

    llm_request.append({"role": "user", "content": content, "step": step_number})

    llm_output = llm_client.chat(llm_request)

    llm_request.append({"role": "assistant", "content": llm_output})


def _get_dict_from_json(json_string : str) -> defaultdict[str, Any]:
    result : dict[str] = defaultdict(str)

    try:
        result = json.loads(json_string)
        result = defaultdict(str, result)

        if _RESPONSE_KEYS != result.keys():
            result["error"] = f"Allowed JSON keys: {', '.join(_RESPONSE_KEYS)}"

    except json.JSONDecodeError as exec:
        result["error"] = exec

    return result


def search_style_guide(query : str) -> None:
    chunks = search(query, _MAX_K)
    chunk_texts = [
        f"{chunk.source_doc_id}: {chunk.text}"
        for chunk in chunks
    ]
    observation = (
        f"Style-guide results for {query!r}:\n\n"
        + "\n\n---\n\n".join(chunk_texts)
    )

    _write_to_llm(observation)


def read_profiles() -> None:
    profiles = [
        f"{path.name} - {path.read_text(encoding='utf-8')}"
        for path in sorted(content_dir.glob("*.md"))
        if path.name != "_template.md"
    ]
    profiles_str = "Content of all profiles:"
    profiles_str += "\n\n".join(profiles)
    profiles_str += "\n\n End of profiles"

    _write_to_llm(profiles_str)


def write_site(html : str) -> None:
    global successful_report

    image_dir = content_dir / "images"
    html = embed_images(html, image_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    report = check_site(html, member_names=member_names_from_content(content_dir))
    print(f"Results of website generation: {report.summary(True)}")
    _write_to_llm(f"Checker report: {report.to_dict()}")

    if 0 == len(report.failures()):
        successful_report = True


def finish(summary : str) -> None:
    global task_done

    if successful_report:
        task_done = True

        print(summary)
    else:
        _write_to_llm(f"Not allowed because there a test that failed")


def loop() -> None:
    global llm_output

    output_dict = _get_dict_from_json(llm_output)

    if "" == output_dict["error"]:
        ## JSON format is valid
        print(f"- {output_dict["thought"]}")

        match output_dict["action"]:
            case "search_style_guide":
                query = output_dict["args"]["query"]

                search_style_guide(query)

            case "read_profiles":
                read_profiles()

            case "finish":
                summary = output_dict["args"]["summary"]

                finish(summary)

            case "write_site":
                _write_to_llm(f"Missing HTML page")

            case _:
                ## Default
                _write_to_llm(f"Unsupported action - Allowed actions: search_style_guide, read_profiles, write_site, finish")

    else:
        if "```html" in llm_output:
            json_text, _, html_part = llm_output.partition("```html")
            html, _, _ = html_part.partition("```")
            json_text = json_text.strip()
            html = html.strip()
            output_dict = _get_dict_from_json(json_text)

            if output_dict["error"]:
                _write_to_llm(f"Problems with your JSON response: {output_dict["error"]}")
            elif "write_site" == output_dict["action"]:
                write_site(html)
            else:
                _write_to_llm(f"Unsupported JSON action with HTML block: {output_dict["action"]}")

        else:
            ## Write the JSON error back to the LLM
            _write_to_llm(f"Problems with your JSON response: {output_dict["error"]}")


def main() -> None:
    global task_done, content_dir, output_path, step_number

    parser = argparse.ArgumentParser()
    parser.add_argument("--content", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    content_dir = args.content.resolve()
    output_path = args.out.resolve()

    create_rag()
    _write_to_llm("Build the final team website for a group.")

    print("")

    while step_number < _MAX_STEPS:
        if not task_done:
            step_number += 1

            print(f"Step: {step_number}")
            loop()

        else:
            print("\n")

            feedback = input("Website feedback (press Enter to finish): ").strip()

            if not feedback:
                task_done = True
                break

            else:
                step_number = 0

                _write_to_llm(f"User feedback about the website: {feedback}")

    ## Nice error message for stopping
    if not task_done:
        print("Abort - Unable to generate website")



if "__main__" == __name__:
    main()
