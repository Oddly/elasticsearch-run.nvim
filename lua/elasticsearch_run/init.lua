-- Main module for elasticsearch-run.nvim
local M = {}

local Config = require("elasticsearch_run.config")

-- Allow Lazy to call require("elasticsearch_run").setup(opts)
function M.setup(opts)
	Config.setup(opts)
end

-- Helper function to find files on runtime path (for internal scripts)
local function rtp_file(rel)
	local matches = vim.api.nvim_get_runtime_file(rel, true)
	if matches and #matches > 0 then
		return matches[1]
	end
	return nil
end

-- State variables for the live-coding window
local live_win_id = nil
local live_buf_id = nil
local popup_win_id = nil
local popup_buf_id = nil
local source_buf_id = nil
-- Get the main buffer ID

-- Helper functions

local function validate_buffer_count()
	if not source_buf_id then
		vim.notify("No source buffer set. Run from a JSON file first.", vim.log.levels.ERROR)
		return nil
	end

	if not vim.api.nvim_buf_is_valid(source_buf_id) then
		vim.notify("Source buffer is no longer valid. Try again.", vim.log.levels.ERROR)
		source_buf_id = nil -- Reset for next time
		return nil
	end

	-- Get full content of source_buf_id buffer
	local lines_to_send = vim.api.nvim_buf_get_lines(source_buf_id, 0, -1, false)
	if #lines_to_send == 0 then
		vim.notify("Buffer is empty. Nothing to simulate.", vim.log.levels.WARN)
		return nil
	end
	return lines_to_send
end

local function create_job(script_path, on_complete)
	local stdout_data, stderr_data = {}, {}

	-- Get the directory of the current buffer for auto-pipeline detection
	local buffer_dir = vim.fn.expand("%:p:h")
	local cmd = { "uv", "run", script_path, "--quiet" }
	
	-- Add --cwd parameter if we have a valid buffer directory
	if buffer_dir and buffer_dir ~= "" and vim.fn.isdirectory(buffer_dir) == 1 then
		table.insert(cmd, "--cwd")
		table.insert(cmd, buffer_dir)
	end

	local job_id = vim.fn.jobstart(cmd, {
		on_stdout = function(_, data)
			if data then
				for _, line in ipairs(data) do
					if line ~= "" then
						table.insert(stdout_data, line)
					end
				end
			end
		end,
		on_stderr = function(_, data)
			if data then
				for _, line in ipairs(data) do
					if line ~= "" then
						table.insert(stderr_data, line)
					end
				end
			end
		end,
		on_exit = function(_, exit_code)
			on_complete(_, exit_code, stdout_data, stderr_data)
		end,
	})
	if job_id == 0 then
		vim.notify("Job failed: invalid arguments", vim.log.levels.ERROR)
		return nil
	elseif job_id == -1 then
		vim.notify("Job failed: command not executable", vim.log.levels.ERROR)
		return nil
	elseif job_id < 0 then
		vim.notify("Job failed: unknown error (code: " .. job_id .. ")", vim.log.levels.ERROR)
		return nil
	end
	return job_id
end
-- M.run: Executes simulation in a floating popup window.

function M.run()
	local cfg = Config.resolve()
	local script_path = cfg.script_path
	
	if not script_path then
		vim.notify("Elasticsearch runner script not found. Check plugin installation.", vim.log.levels.ERROR)
		return
	end

	-- Prevent sending the popup contents if again running in the popup
	-- Only set source_buf_id if we don't have one or if current buffer is not a popup
	if not source_buf_id or not vim.api.nvim_buf_is_valid(source_buf_id) then
		source_buf_id = vim.api.nvim_get_current_buf()
	elseif vim.api.nvim_get_current_buf() ~= popup_buf_id then
		-- User is in a different buffer (not the popup), update source
		source_buf_id = vim.api.nvim_get_current_buf()
	end

	local lines_to_send = validate_buffer_count()

	if not lines_to_send then
		return
	end

	-- vim.notify("Running Elasticsearch pipeline simulatio...", vim.log.levels.INFO)
	local job_id = create_job(script_path, function(_, exit_code, stdout_data, stderr_data)
		vim.schedule(function()
			local display_data, title
			if exit_code == 0 then
				title = "Pipeline Simulation: SUCCESS"
				display_data = stdout_data
			else
				title = "Pipeline Simulation: FAILURE (Exit Code: " .. exit_code .. ")"
				display_data = { "--- STDERR ---" }
				for _, line in ipairs(stderr_data) do
					table.insert(display_data, line)
				end

				if #stdout_data > 0 then
					table.insert(display_data, "--- STDOUT ---")
					for _, line in ipairs(stdout_data) do
						table.insert(display_data, line)
					end
				end

				if #display_data <= 1 then
					table.insert(display_data, "Script failed with no output.")
				end
			end

			local width = math.floor(vim.o.columns * 0.8)
			local height = math.min(#display_data + 4, math.floor(vim.o.lines * 0.8))
			local row = math.floor((vim.o.lines - height) / 2)
			local col = math.floor((vim.o.columns - width) / 2)
			local output_buf

			-- Set properties for output_buf
			local opts = {
				relative = "editor",
				width = width,
				height = height,
				row = row,
				col = col,
				style = "minimal",
				border = "single",
				title = title,
				title_pos = "center",
			}

			-- recreate the popup buffer if it doesn't exist or isn't valid
			if not popup_buf_id or not vim.api.nvim_buf_is_valid(popup_buf_id) then
				popup_buf_id = vim.api.nvim_create_buf(true, true)
			end

			-- if the popup window exists and is valid...
			if popup_win_id and vim.api.nvim_win_is_valid(popup_win_id) then
				-- refresh the popup window size/position/title
				vim.api.nvim_win_set_config(popup_win_id, opts)
				-- load the popup buffer in the popup window
				if vim.api.nvim_win_get_buf(popup_win_id) ~= popup_buf_id then
					vim.api.nvim_win_set_buf(popup_win_id, popup_buf_id)
				end
				-- Bring popup window to front
				vim.api.nvim_win_set_config(popup_win_id, vim.tbl_extend("force", opts, { zindex = 200 }))
			-- if no popup window exists or is valid...
			else
				-- open a new popup window
				popup_win_id = vim.api.nvim_open_win(popup_buf_id, true, opts)
				-- make sure the popup_win_id is deleted if the window is closed
				vim.api.nvim_create_autocmd("WinClosed", {
					pattern = tostring(popup_win_id),
					callback = function()
						popup_win_id = nil
					end,
				})
			end

			if exit_code == 0 then
				-- Set json filetype for popup_buffer
				vim.api.nvim_set_option_value("filetype", "json", { buf = popup_buf_id })
			else
				-- Set log filetype for popup buffer
				vim.api.nvim_set_option_value("filetype", "log", { buf = popup_buf_id })
			end
			vim.api.nvim_buf_set_lines(popup_buf_id, 0, -1, false, display_data)
		end)
	end)

	if not job_id or job_id <= 0 then
		vim.notify("Failed to start script job.", vim.log.levels.ERROR)
		return
	end

	vim.api.nvim_chan_send(job_id, table.concat(lines_to_send, "\n"))
	vim.fn.chanclose(job_id, "stdin")
end

-- M.run_with_logstash: Executes simulation with Logstash preprocessing in a floating popup window.
function M.run_with_logstash()
	local cfg = Config.resolve()
	local script_path = cfg.script_path
	
	if not script_path then
		vim.notify("Elasticsearch runner script not found. Check plugin installation.", vim.log.levels.ERROR)
		return
	end

	-- Prevent sending the popup contents if again running in the popup
	-- Only set source_buf_id if we don't have one or if current buffer is not a popup
	if not source_buf_id or not vim.api.nvim_buf_is_valid(source_buf_id) then
		source_buf_id = vim.api.nvim_get_current_buf()
	elseif vim.api.nvim_get_current_buf() ~= popup_buf_id then
		-- User is in a different buffer (not the popup), update source
		source_buf_id = vim.api.nvim_get_current_buf()
	end

	local lines_to_send = validate_buffer_count()

	if not lines_to_send then
		return
	end

	-- Use the main Python script (it handles Logstash internally)
	local job_id = create_job(script_path, function(_, exit_code, stdout_data, stderr_data)
		vim.schedule(function()
			local display_data, title
			if exit_code == 0 then
				title = "Logstash → Elasticsearch Pipeline: SUCCESS"
				display_data = stdout_data
			else
				title = "Logstash → Elasticsearch Pipeline: FAILURE (Exit Code: " .. exit_code .. ")"
				display_data = { "--- STDERR ---" }
				for _, line in ipairs(stderr_data) do
					table.insert(display_data, line)
				end

				if #stdout_data > 0 then
					table.insert(display_data, "--- STDOUT ---")
					for _, line in ipairs(stdout_data) do
						table.insert(display_data, line)
					end
				end

				if #display_data <= 1 then
					table.insert(display_data, "Logstash processing failed with no output.")
				end
			end

			local width = math.floor(vim.o.columns * 0.8)
			local height = math.min(#display_data + 4, math.floor(vim.o.lines * 0.8))
			local row = math.floor((vim.o.lines - height) / 2)
			local col = math.floor((vim.o.columns - width) / 2)

			-- Set properties for output_buf
			local opts = {
				relative = "editor",
				width = width,
				height = height,
				row = row,
				col = col,
				style = "minimal",
				border = "single",
				title = title,
				title_pos = "center",
			}

			-- recreate the popup buffer if it doesn't exist or isn't valid
			if not popup_buf_id or not vim.api.nvim_buf_is_valid(popup_buf_id) then
				popup_buf_id = vim.api.nvim_create_buf(true, true)
			end

			-- if the popup window exists and is valid...
			if popup_win_id and vim.api.nvim_win_is_valid(popup_win_id) then
				-- refresh the popup window size/position/title
				vim.api.nvim_win_set_config(popup_win_id, opts)
				-- load the popup buffer in the popup window
				if vim.api.nvim_win_get_buf(popup_win_id) ~= popup_buf_id then
					vim.api.nvim_win_set_buf(popup_win_id, popup_buf_id)
				end
				-- Bring popup window to front
				vim.api.nvim_win_set_config(popup_win_id, vim.tbl_extend("force", opts, { zindex = 200 }))
			-- if no popup window exists or is valid...
			else
				-- open a new popup window
				popup_win_id = vim.api.nvim_open_win(popup_buf_id, true, opts)
				-- make sure the popup_win_id is deleted if the window is closed
				vim.api.nvim_create_autocmd("WinClosed", {
					pattern = tostring(popup_win_id),
					callback = function()
						popup_win_id = nil
					end,
				})
			end

			if exit_code == 0 then
				-- Set json filetype for popup_buffer
				vim.api.nvim_set_option_value("filetype", "json", { buf = popup_buf_id })
			else
				-- Set log filetype for popup buffer
				vim.api.nvim_set_option_value("filetype", "log", { buf = popup_buf_id })
			end
			vim.api.nvim_buf_set_lines(popup_buf_id, 0, -1, false, display_data)
		end)
	end)

	if not job_id or job_id <= 0 then
		vim.notify("Failed to start Logstash batch processor job.", vim.log.levels.ERROR)
		return
	end

	vim.api.nvim_chan_send(job_id, table.concat(lines_to_send, "\n"))
	vim.fn.chanclose(job_id, "stdin")
end

function M.live_run()
	local cfg = Config.resolve()
	local script_path = cfg.script_path
	
	if not script_path then
		vim.notify("Elasticsearch runner script not found. Check plugin installation.", vim.log.levels.ERROR)
		return
	end

	-- Prevent sending contents from the live or popup buffer
	-- Only set source_buf_id if we don't have one or if current buffer is not an output buffer
	local current_buf = vim.api.nvim_get_current_buf()
	if not source_buf_id or not vim.api.nvim_buf_is_valid(source_buf_id) then
		if current_buf ~= live_buf_id and current_buf ~= popup_buf_id then
			source_buf_id = current_buf
		end
	elseif current_buf ~= live_buf_id and current_buf ~= popup_buf_id then
		-- User is in a different buffer (not the live or popup output), update source
		source_buf_id = current_buf
	end

	local lines_to_send = validate_buffer_count()
	if not lines_to_send then
		return
	end

	local job_id = create_job(script_path, function(_, exit_code, stdout_data, stderr_data)
		vim.schedule(function()
			-- Ensure live window and buffer exist
			if not (live_win_id and vim.api.nvim_win_is_valid(live_win_id)) then
				local prev_win = vim.api.nvim_get_current_win()
				vim.cmd("100vsplit")
				live_win_id = vim.api.nvim_get_current_win()

				-- Create/recreate the live buffer if needed
				if not live_buf_id or not vim.api.nvim_buf_is_valid(live_buf_id) then
					live_buf_id = vim.api.nvim_create_buf(false, true) -- unlisted scratch
					vim.api.nvim_set_option_value("buftype", "nofile", { buf = live_buf_id })
					vim.api.nvim_set_option_value("bufhidden", "hide", { buf = live_buf_id })
					vim.api.nvim_set_option_value("swapfile", false, { buf = live_buf_id })
					vim.api.nvim_buf_set_name(live_buf_id, "Pipeline_Output")
				end

				vim.api.nvim_win_set_buf(live_win_id, live_buf_id)
				vim.api.nvim_set_current_win(prev_win)

				-- Track window lifetime
				vim.api.nvim_create_autocmd("WinClosed", {
					pattern = tostring(live_win_id),
					callback = function()
						live_win_id = nil
					end,
				})
			else
				-- Window exists; ensure buffer exists and is attached
				if not live_buf_id or not vim.api.nvim_buf_is_valid(live_buf_id) then
					live_buf_id = vim.api.nvim_create_buf(false, true)
					vim.api.nvim_set_option_value("buftype", "nofile", { buf = live_buf_id })
					vim.api.nvim_set_option_value("bufhidden", "hide", { buf = live_buf_id })
					vim.api.nvim_set_option_value("swapfile", false, { buf = live_buf_id })
					vim.api.nvim_buf_set_name(live_buf_id, "Pipeline_Output")
				end
				if vim.api.nvim_win_get_buf(live_win_id) ~= live_buf_id then
					vim.api.nvim_win_set_buf(live_win_id, live_buf_id)
				end
			end

			-- Build display data like M.run
			local display_data
			local ft
			if exit_code == 0 then
				display_data = stdout_data
				ft = "json"
			else
				display_data = { "--- STDERR ---" }
				for _, line in ipairs(stderr_data) do
					table.insert(display_data, line)
				end
				if #stdout_data > 0 then
					table.insert(display_data, "--- STDOUT ---")
					for _, line in ipairs(stdout_data) do
						table.insert(display_data, line)
					end
				end
				if #display_data <= 1 then
					table.insert(display_data, "Script failed with no output.")
				end
				ft = "log"
			end

			vim.api.nvim_set_option_value("filetype", ft, { buf = live_buf_id })
			vim.api.nvim_buf_set_lines(live_buf_id, 0, -1, false, display_data)
		end)
	end)

	if not job_id or job_id <= 0 then
		vim.notify("Failed to start script job.", vim.log.levels.ERROR)
		return
	end

	vim.api.nvim_chan_send(job_id, table.concat(lines_to_send, "\n"))
	vim.fn.chanclose(job_id, "stdin")
end

return M
