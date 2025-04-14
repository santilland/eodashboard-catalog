import os
import yaml
from yaml.loader import SafeLoader
import json

json_collections_path = "collections/"
collections_path = "yaml_collections/"

json_indicators_path = "indicators/"
indicators_path = "yaml_indicators/"

catalog_path = "catalogs/trilateral.yaml"

ALL_CHANGED_FILES = os.environ.get("ALL_CHANGED_FILES")
changed_files = ALL_CHANGED_FILES.split(" ")
print("ALL_CHANGED_FILES: ", changed_files)

collections_files = [
    file for file in changed_files if file.startswith(json_collections_path)
]
indicator_files = [
    file for file in changed_files if file.startswith(json_indicators_path)
]

print("changed collections files: ", collections_files)
print("changed indicator files: ", indicator_files)
# convert json to yaml and move to their respective folders
for i, file in enumerate(collections_files):
    with open(file, "r") as f:
        collection = json.load(f)
        respective_file = collections_path + file.split("/")[-1].split(".")[0] + ".yaml"
        os.makedirs(os.path.dirname(respective_file))
        with open(respective_file, "w") as f:
            yaml.dump(collection, f)
        collections_files[i] = respective_file

for i, file in enumerate(indicator_files):
    with open(file, "r") as f:
        collection = json.load(f)
        respective_file = indicators_path + file.split("/")[-1].split(".")[0] + ".yaml"
        os.makedirs(os.path.dirname(respective_file))
        with open(respective_file, "w") as f:
            yaml.dump(collection, f)
        indicator_files[i] = respective_file


is_indicator = {file: False for file in collections_files}

# if the changed collection files doesnt exist in an indicator file, add it to the catalog
for file in indicator_files:
    with open(file, "r") as f:
        indicator = yaml.load(f, Loader=SafeLoader)
        if "Collections" not in indicator:
            continue
    for collection in indicator["Collections"]:
        if collection in collections_files:
            is_indicator[collection] = True

with open(catalog_path, "r") as f:
    catalog = yaml.load(f, Loader=SafeLoader)
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
    yaml.dump(catalog, f)
