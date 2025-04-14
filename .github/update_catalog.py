import os
from yaml import load, dump
from yaml.loader import SafeLoader
import json

collections_path = "collections/"
indicators_path = "indicators/"
catalog_path = "catalogs/trilateral.yaml"

ALL_CHANGED_FILES = os.environ.get("ALL_CHANGED_FILES")
changed_files = ALL_CHANGED_FILES.split(" ")
print("ALL_CHANGED_FILES: ", changed_files)

collections_files = [
    file for file in changed_files if file.startswith(collections_path)
]
indicator_files = [file for file in changed_files if file.startswith(indicators_path)]

print("changed collections files: ", collections_files)

is_indicator = {file: False for file in collections_files}

print("changed indicator files: ", indicator_files)
# if the changed collection files doesnt exist in an indicator file, add it to the catalog
for file in indicator_files:
    with open(file, "r") as f:
        indicator = json.load(f)
        if "Collections" not in indicator:
            continue
    for collection in indicator["Collections"]:
        if collection in collections_files:
            is_indicator[collection] = True
with open(catalog_path, "r") as f:
    catalog = load(f, Loader=SafeLoader)
    catalog["collections"] = []
    for key in is_indicator:
        if not is_indicator[key]:
            key = key.split("/")[-1].split(".")[0]
            catalog["collections"].append(key)

    for file in indicator_files:
        file = file.split("/")[-1].split(".")[0]
        catalog["collections"].append(file)


with open(catalog_path, "w") as f:
    print("adding the following as indicators to the catalog: ", catalog["collections"])
    dump(catalog, f)
