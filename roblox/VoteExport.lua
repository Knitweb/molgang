--!strict
-- MOLGANG VoteExport — accumulate settled rounds and hand them to the knitweb bridge once
-- an hour. The export JSON matches exactly what `bridge/ingest.py` ingests, so the bridge can
-- map each unique Roblox wallet id to a stable knitweb account and weave the votes in.
-- ServerScript/ModuleScript under ServerScriptService (needs HttpService enabled).

local HttpService = game:GetService("HttpService")

local VoteExport = {}
VoteExport.rounds = {} :: { any }

-- Record a settled round (call from Game flow after Game.settle).
function VoteExport.record(round)
	table.insert(VoteExport.rounds, {
		bond = { formula = round.bond.formula, name = round.bond.name },
		proposer_roblox_id = round.proposer.robloxId,
		votes = round.votes, -- array of { roblox_id, verdict }
	})
end

-- Serialize to the bridge's format (see bridge/sample_roblox_votes.json).
function VoteExport.toJSON(): string
	return HttpService:JSONEncode({
		exported_at = os.date("!%Y-%m-%dT%H:%M:%SZ"),
		source = "molgang-roblox",
		rounds = VoteExport.rounds,
	})
end

-- Every hour: POST the accumulated votes to the bridge endpoint, then clear the buffer.
-- `endpointUrl` is a small ingestion service that runs `bridge/ingest.py` server-side.
function VoteExport.startHourlyExport(endpointUrl: string)
	task.spawn(function()
		while true do
			task.wait(3600) -- one hour
			if #VoteExport.rounds > 0 then
				local payload = VoteExport.toJSON()
				local ok, err = pcall(function()
					HttpService:PostAsync(endpointUrl, payload, Enum.HttpContentType.ApplicationJson)
				end)
				if ok then
					VoteExport.rounds = {} -- weaving succeeded; start a fresh hour
				else
					warn("MOLGANG export failed, will retry next hour: " .. tostring(err))
				end
			end
		end
	end)
end

return VoteExport
