-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Regionally Famous contributors

local process = require("wf.api.v1.process")
local superfamiconv = require("wf.api.v1.process.tools.superfamiconv")

local files = process.inputs("dialbug-sd-mascot-v5.png")
for _, file in pairs(files) do
	local tilemap = superfamiconv.convert_tilemap(
		file,
		superfamiconv.config()
			:mode("wsc"):bpp(2)
			:color_zero("#00091e")
			:tile_base(0):palette_base(6)
	)
	process.emit_symbol("gfx_dialbug_mascot", tilemap)
end
