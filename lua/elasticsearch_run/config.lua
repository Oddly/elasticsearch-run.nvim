-- Config and path resolution for elasticsearch-run.nvim
-- Searches only inside this plugin (via runtimepath). No fallback to ~/.config/nvim.
-- Users can still override absolute paths via setup().

---@class ElasticsearchRunConfig
---@field script_path string|nil Absolute path override for the bash runner script.
---@field es_manager_path string|nil Absolute path override for the Python container manager.

---@class ElasticsearchRunResolved
---@field script_path string|nil Resolved runner script path, or nil if not found in the plugin (and no override provided).
---@field es_manager_path string|nil Resolved container manager path, or nil if not found in the plugin (and no override provided).

local M = {
  -- User-overridable options (set via setup()).
  script_path = nil,
  es_manager_path = nil,
}

---Find the first matching file on Neovim's runtimepath.
---Only used to locate files bundled inside this plugin (e.g. scripts/elasticsearch_run/*).
---@param rel string Path relative to an rtp root, e.g. "scripts/elasticsearch_run/es_simulate_runner.sh".
---@return string|nil abs_path Absolute path if found, otherwise nil.
local function rtp_file(rel)
  local matches = vim.api.nvim_get_runtime_file(rel, true)
  if matches and #matches > 0 then
    return matches[1]
  end
  return nil
end

---Resolve effective configuration:
--- 1) User overrides from setup() (absolute paths)
--- 2) Files bundled in this plugin (found on runtimepath)
---@return ElasticsearchRunResolved cfg
function M.resolve()
  local cfg = {}

  cfg.script_path = M.script_path
    or rtp_file("scripts/elasticsearch_run/es_simulate_runner.sh")

  cfg.es_manager_path = M.es_manager_path
    or rtp_file("scripts/elasticsearch_run/manage_es_container.py")

  return cfg
end

---Set user overrides for config options.
---Call from your plugin spec’s config(), or use Lazy's opts/config=true with main="elasticsearch_run".
---@param opts ElasticsearchRunConfig|nil
function M.setup(opts)
  if type(opts) == "table" then
    for k, v in pairs(opts) do
      M[k] = v
    end
  end
end

return M
