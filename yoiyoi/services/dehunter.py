import re

# parse json
import orjson

CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+/"


def convert_base(source_string, source_base, target_base):
    BASE_ARRAY = list(CHARS)
    SOURCE_ARRAY = BASE_ARRAY[0:source_base]
    accumulator = 0
    for i, char in enumerate(reversed(source_string)):
        try:
            index = SOURCE_ARRAY.index(char)
            accumulator += index * source_base**i
        except ValueError:
            continue
    TARGET_ARRAY = BASE_ARRAY[0:target_base]
    target_string = []
    while accumulator > 0:
        target_string.append(TARGET_ARRAY[accumulator % target_base])
        accumulator //= target_base
    return target_string and int("".join(reversed(target_string))) or 0


def hunter(input_string, delimiter, target_offset, source_base):
    source_string, target_string = 0, []
    flag = delimiter[source_base]
    for ch in input_string:
        if ch != flag:
            try:
                source_string = source_string * 10 + delimiter.index(ch)
            except ValueError:
                source_string = source_string * 10 + int(ch)
            continue
        target_string.append(
            chr(convert_base(str(source_string), source_base, 10) - target_offset)
        )
        source_string = 0
    return "".join(target_string)


def dehunter(string: bytes | str):
    if isinstance(string, bytes):
        string = string.decode("utf-8")
    args = re.search(
        r"\(\"(?P<input>[^\"]+)\",\d+,\"(?P<delim>[^\"]+)\",(?P<offset>\d+),(?P<source>\d+),\d+\)\)$",
        string,
    )
    if not args:
        return None, {"status": "failed"}
    response = hunter(
        args["input"], args["delim"], int(args["offset"]), int(args["source"])
    )
    if result := re.search(
        r"(?P<html><[a-zA-Z]+.+>)?\s*\";[^{]+(?P<status>{ \"status\".+?})?", response
    ):
        return result["html"], orjson.loads(result["status"]) if result["status"] else {}
