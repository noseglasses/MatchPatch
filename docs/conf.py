project = "MatchPatch"

extensions = [
    "myst_parser",
]

source_suffix = {
    ".md": "markdown",
}
root_doc = "index"

exclude_patterns = [
    "assets/screenshots/README.md",
]

html_theme = "furo"
html_title = "MatchPatch Documentation"
html_extra_path = [
    "assets",
]
