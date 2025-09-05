-- Guard against double load
if vim.g.loaded_elasticsearch_run then
  return
end
vim.g.loaded_elasticsearch_run = true

local ns = "elasticsearch_run"

local function req(mod)
  return require(ns .. "." .. mod)
end

-- Commands
do
  vim.api.nvim_create_user_command("ElasticRun", function()
    local ok, m = pcall(require, ns)
    if ok and type(m.run) == "function" then
      m.run()
    else
      vim.notify("elasticsearch_run.run() not found", vim.log.levels.WARN)
    end
  end, { desc = "Run ES pipeline (popup)" })

  vim.api.nvim_create_user_command("ElasticLive", function()
    local ok, m = pcall(require, ns)
    if ok and type(m.live_run) == "function" then
      m.live_run()
    else
      vim.notify("elasticsearch_run.live_run() not found", vim.log.levels.WARN)
    end
  end, { desc = "Live-run ES pipeline (vsplit)" })

  vim.api.nvim_create_user_command("ESContainerDestroy", function()
    local cfg = req("config").resolve() -- resolve at call time
    if not (cfg.es_manager_path and vim.uv.fs_stat(cfg.es_manager_path)) then
      vim.notify("ES manager script not found in plugin (scripts/elasticsearch_run/manage_es_container.py)", vim.log.levels.ERROR)
      return
    end
    vim.fn.jobstart({ "uv", "run", cfg.es_manager_path, "destroy" }, { detach = true })
  end, { desc = "Stops and removes the ES container and its data volume." })
end

-- Autorun on InsertLeave when live output window is open
do
  local group = vim.api.nvim_create_augroup("ESRunLiveAutorun", { clear = true })
  vim.api.nvim_create_autocmd("InsertLeave", {
    group = group,
    pattern = "*.json",
    callback = function()
      local live_open = false
      for _, win in ipairs(vim.api.nvim_list_wins()) do
        local buf = vim.api.nvim_win_get_buf(win)
        local name = vim.api.nvim_buf_get_name(buf)
        if name:match("Pipeline_Output") then
          live_open = true
          break
        end
      end
      if not live_open then return end
      local ok, m = pcall(require, ns)
      if ok and type(m.live_run) == "function" then
        m.live_run()
      end
    end,
  })
end

-- Keymaps
do
  local map = vim.keymap.set
  map("n", "<leader>p", "<cmd>ElasticRun<CR>", { desc = "Run ES pipeline (popup)", silent = true })
  map("n", "<leader>R", "<cmd>ElasticLive<CR>", { desc = "Live-run ES pipeline (vsplit)", silent = true })
end

-- Tooling help
vim.api.nvim_create_user_command("ElasticToolsHelp", function()
  local lines = {
    "Prerequisites:",
    "- bash, curl, jq",
    "- uv (https://docs.astral.sh/uv/): curl -fsSL https://astral.sh/uv/install.sh | sh",
    "- Docker: install per OS, ensure 'docker ps' works without sudo",
    "",
    "Run :checkhealth elasticsearch_run to verify.",
  }
  vim.notify(table.concat(lines, "\n"), vim.log.levels.INFO, { title = "Elastic Run Tools" })
end, { desc = "Show install hints for required tools" })
