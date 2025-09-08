-- Config and path resolution for elasticsearch-run.nvim
-- Searches only inside this plugin (via runtimepath). No fallback to ~/.config/nvim.
-- Users can still override absolute paths via setup().

---@class ElasticsearchRunConfig
---@field script_path string|nil Absolute path override for the bash runner script.
---@field es_manager_path string|nil Absolute path override for the Python container manager.
---@field logstash_manager_path string|nil Absolute path override for the Logstash container manager.
---@field elasticsearch_version string|nil Version tag for Elasticsearch container (e.g. "8.15.0", "latest").
---@field logstash_version string|nil Version tag for Logstash container (e.g. "8.15.0", "latest").
---@field elasticsearch_image string|nil Full Docker image override for Elasticsearch (overrides version if set).
---@field logstash_image string|nil Full Docker image override for Logstash (overrides version if set).

---@class ElasticsearchRunResolved
---@field script_path string|nil Resolved runner script path, or nil if not found in the plugin (and no override provided).
---@field es_manager_path string|nil Resolved container manager path, or nil if not found in the plugin (and no override provided).
---@field logstash_manager_path string|nil Resolved Logstash container manager path, or nil if not found in the plugin (and no override provided).
---@field elasticsearch_image string Docker image for Elasticsearch container.
---@field logstash_image string Docker image for Logstash container.

local M = {
  -- User-overridable options (set via setup()).
  script_path = nil,
  es_manager_path = nil,
  logstash_manager_path = nil,
  -- Default versions
  elasticsearch_version = "latest",
  logstash_version = "latest",
  -- Full image overrides (optional)
  elasticsearch_image = nil,
  logstash_image = nil,
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

  cfg.logstash_manager_path = M.logstash_manager_path
    or rtp_file("scripts/elasticsearch_run/manage_logstash_container.py")

  -- Docker images: use full image override or build from version
  cfg.elasticsearch_image = M.elasticsearch_image 
    or ("docker.elastic.co/elasticsearch/elasticsearch:" .. M.elasticsearch_version)
  cfg.logstash_image = M.logstash_image 
    or ("docker.elastic.co/logstash/logstash:" .. M.logstash_version)

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
