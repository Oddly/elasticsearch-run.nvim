# elasticsearch-run.nvim

Elasticsearch pipeline runner for Neovim.

Prereqs: bash, curl, jq, uv, docker.
Run :checkhealth elasticsearch_run to verify.

Usage:
- <leader>p — Run (popup)
- <leader>R — Live-run (vsplit)
- :ElasticRun / :ElasticLive
- :ESContainerDestroy — Stop/remove ES container (optional helper)
- :ElasticToolsHelp — Install hints
