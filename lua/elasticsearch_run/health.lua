local health = vim.health or require("health")

local function bin(name)
  return vim.fn.executable(name) == 1
end

return {
  check = function()
    health.start("elasticsearch-run.nvim: dependencies")
    if bin("bash") then health.ok("bash found") else health.error("bash not found") end
    if bin("curl") then health.ok("curl found") else health.error("curl not found") end
    if bin("jq") then health.ok("jq found") else health.warn("jq not found (pretty output disabled)") end
    if bin("uv") then health.ok("uv found") else health.warn("uv not found (container helpers will fail)") end
    if bin("docker") then health.ok("docker found") else health.warn("docker not found (container helpers will fail)") end

    health.start("elasticsearch-run.nvim: files")
    local cfg = require("elasticsearch_run.config").resolve()

    if cfg.script_path and vim.uv.fs_stat(cfg.script_path) then
      health.ok("runner script: " .. cfg.script_path)
    else
      health.error("runner script missing (expected inside the plugin at scripts/elasticsearch_run/es_simulate_runner.sh)")
    end

    if cfg.es_manager_path and vim.uv.fs_stat(cfg.es_manager_path) then
      health.ok("es manager: " .. cfg.es_manager_path)
    else
      health.warn("es manager missing (only needed for :ESContainerDestroy and related container commands)")
    end
  end,
}
