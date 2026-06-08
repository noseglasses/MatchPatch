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
html_logo = "assets/matchmatch-logo.png"
html_favicon = "assets/matchmatch-icon-512.png"
html_static_path = [
    "_static",
]
html_css_files = [
    "matchpatch-docs.css",
]
html_extra_path = [
    "assets",
]
