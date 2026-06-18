--!strict
-- MOLGANG Sync — the two-way bridge client, alternating every 30 minutes.
--   even tick → UPLOAD   : POST the buffered votes (Roblox → Knitweb)
--   odd  tick → DOWNLOAD : GET the knitweb snapshot and apply it (Knitweb → molgang)
-- So each direction syncs hourly and something syncs every 30 min — never both in one tick.
-- ServerScript under ServerScriptService (HTTP Requests enabled). Mirrors bridge/sync.py.

local HttpService = game:GetService("HttpService")
local VoteExport = require(script.Parent.VoteExport)

local Sync = {}
Sync.confirmed = {} :: { [string]: boolean } -- canonical woven bonds from the knitweb
Sync.web = {} :: { any }
Sync.players = {} :: { any }

-- Apply a downloaded knitweb snapshot (same shape as bridge/snapshot.py output):
-- which bonds are canonically confirmed network-wide (incl. the Python P2P game), and the
-- continued player balances. The UI can use Sync.isConfirmed(formula) and Sync.players.
function Sync.applySnapshot(snap)
	local confirmed = {}
	for _, formula in ipairs(snap.confirmed_formulas or {}) do
		confirmed[formula] = true
	end
	Sync.confirmed = confirmed
	Sync.web = snap.web or {}
	Sync.players = snap.players or {}
end

function Sync.isConfirmed(formula: string): boolean
	return Sync.confirmed[formula] == true
end

-- Start the alternating 30-minute loop. `uploadUrl` runs `bridge/sync.py` upload-side;
-- `downloadUrl` serves the latest `outbox_snapshot.json`.
function Sync.start(uploadUrl: string, downloadUrl: string)
	task.spawn(function()
		local tick = 0
		while true do
			task.wait(1800) -- 30 minutes
			if tick % 2 == 0 then
				-- UPLOAD (Roblox → Knitweb)
				if #VoteExport.rounds > 0 then
					local payload = VoteExport.toJSON()
					local ok, err = pcall(function()
						HttpService:PostAsync(uploadUrl, payload, Enum.HttpContentType.ApplicationJson)
					end)
					if ok then
						VoteExport.rounds = {}
					else
						warn("MOLGANG upload failed (retry in 1h): " .. tostring(err))
					end
				end
			else
				-- DOWNLOAD (Knitweb → molgang)
				local ok, body = pcall(function() return HttpService:GetAsync(downloadUrl) end)
				if ok then
					local okj, snap = pcall(function() return HttpService:JSONDecode(body) end)
					if okj then Sync.applySnapshot(snap) end
				else
					warn("MOLGANG download failed (retry in 1h): " .. tostring(body))
				end
			end
			tick += 1
		end
	end)
end

return Sync
