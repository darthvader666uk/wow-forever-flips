"""Install the FlipLists addon: it replaces the Auctionator shopping lists in
lists.txt on every login or /reload, so no manual import is needed."""

import json
import os
import sqlite3
from pathlib import Path

from ah_pull import DEFAULT, HOUSES, db_path, load_summary
from blizzard import item_ids, money

HERE = Path(__file__).parent
SOURCE = HERE / "lists.txt"
# Where to write the addon: your AddOns/FlipLists folder, or dist/FlipLists (the release build)
ADDON = Path(os.environ.get("FLIPLISTS_ADDON") or HERE / "dist" / "FlipLists")

TOC = """## Interface: 16001
## Title: Flip Lists
## Notes: Replaces the Flip shopping lists in Auctionator from Lists.lua on every login or /reload.
## Dependencies: Auctionator
## OptionalDeps: PointBlankSniper
## SavedVariables: FlipListsDB
## SavedVariablesPerCharacter: FlipListsCharDB
Lists.lua
FlipLists.lua
Tab.xml
"""

# Auctionator builds its list manager on its own ADDON_LOADED, so it is ready by PLAYER_LOGIN.
# CreateShoppingList deletes a list of the same name first, so this is a clean replace.
# POISONS: rogue poisons the Forever server will not buy, though item data gives a vendor price.
# Point Blank Sniper skips any item ID in its VendorBlacklist table, so add them there.
MAIN = r"""local POISONS = {
  6947, 6949, 6950, 8926, 8927, 8928,     -- Instant Poison I-VI
  2892, 2893, 8984, 8985, 20844,          -- Deadly Poison I-V
  10918, 10920, 10921, 10922,             -- Wound Poison I-IV
  3775, 3776,                             -- Crippling Poison I-II
  5237, 6951, 9186,                       -- Mind-numbing Poison I-III
  217345, 217346, 217347, 226374, 234444, -- Sebacious, Numbing, Atrophic, Occult I-II
}

local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_LOGIN")
-- Snipe caps and prices come from the hourly AH pull, but the game only reads Lists.lua on a
-- /reload. When the AH opens with data over 75 minutes old, a newer file is almost certainly
-- waiting, so say so. If it still says so straight after a /reload, the hourly pull has stopped.
local STALE = 75 * 60
local stale = CreateFrame("Frame")
stale:RegisterEvent("AUCTION_HOUSE_SHOW")
stale:SetScript("OnEvent", function()
  local age = FlipLists_Updated and time() - FlipLists_Updated
  if age and age > STALE then
    print(format("|cffff5555Flip Lists:|r Snipe caps use AH data from %s (%dh %02dm old). /reload loads newer ones.",
      date("%H:%M", FlipLists_Updated), floor(age / 3600), floor(age % 3600 / 60)))
  end
end)

-- Forever has one auction house per realm type and faction, and Lists.lua carries the snipe
-- caps and prices of each (FlipLists_Houses). The game does not tell addons the realm type, so
-- it is picked once per character in the settings (Normal until then). Faction is automatic.
-- Same mapping as HOUSES in ah_pull.py: {Alliance, Horde}.
local HOUSES = {Normal = {111, 114}, PvP = {110, 113}, RP = {119, 120}, ["RP-PvP"] = {123, 124}}
local RULESETS = {"Normal", "PvP", "RP", "RP-PvP"}

local function LoadLists()
  FlipListsCharDB = FlipListsCharDB or {}
  local ruleset = HOUSES[FlipListsCharDB.ruleset] and FlipListsCharDB.ruleset or "Normal"
  local faction = UnitFactionGroup("player") == "Horde" and "Horde" or "Alliance"
  local house = FlipLists_Houses[HOUSES[ruleset][faction == "Horde" and 2 or 1]] or {}
  FlipLists_Prices, FlipLists_Updated = house.prices or {}, house.updated
  local names = {}
  for name, items in pairs(FlipLists_Data) do
    if name == "Flip Snipe" and house.snipe then items = house.snipe end  -- the same items, with caps
    Auctionator.API.v1.CreateShoppingList("FlipLists", name, items)
    table.insert(names, name .. " (" .. #items .. ")")
  end
  table.sort(names)
  local from = FlipLists_Updated and (", " .. ruleset .. " " .. faction .. " AH data from " ..
    date("%H:%M", FlipLists_Updated)) or (", no " .. ruleset .. " " .. faction .. " AH data yet")
  print("|cff00ff00Flip Lists:|r updated " .. table.concat(names, ", ") .. from)
  if not FlipListsCharDB.ruleset then
    print("|cffffff00Flip Lists:|r using Normal realm prices. If your realm is PvP, RP or RP-PvP, " ..
      "pick it once in Esc > Options > AddOns > Flip Lists.")
  end
end

f:SetScript("OnEvent", function()
  LoadLists()

  local blacklist = PointBlankSniper and PointBlankSniper.Constants.VendorBlacklist
  if blacklist then
    for _, id in ipairs(POISONS) do
      if not tContains(blacklist, id) then table.insert(blacklist, id) end
    end
    print("|cff00ff00Flip Lists:|r Point Blank Sniper now skips " .. #POISONS .. " rogue poisons")
  end
end)

-- After a purchase, restart the Point Blank Sniper scan (scanning needs no click, buying does).
-- Only while its tab is on screen, so buying through Auctionator's own tabs is left alone.
local rescan = CreateFrame("Frame")
for _, event in ipairs({"COMMODITY_PURCHASE_SUCCEEDED", "AUCTION_HOUSE_PURCHASE_COMPLETED"}) do
  pcall(rescan.RegisterEvent, rescan, event)
end
local lastRestart = 0
local function Restart()  -- a buy and the "Sold" that follows it can both ask, so start once
  C_Timer.After(1, function()
    local tab = PointBlankSniperTabFrame
    if tab and tab:IsVisible() and GetTime() - lastRestart > 2 then
      lastRestart = GetTime()
      tab:Start()
    end
  end)
end
rescan:SetScript("OnEvent", Restart)

-- While PBS's buy panel is open, the scroll wheel presses its Buy button. Each wheel click is
-- your own input, like clicking Buy, and PBS still refuses anything over the price cap. Also
-- restart the scan when the panel shows "Sold" (someone beat you to it) so scanning never stalls.
local wheelBuy = CreateFrame("Button", "FlipListsWheelBuy")
local function WireBuyPanel()
  local buy = PointBlankSniperTabFrame and PointBlankSniperTabFrame.Buy
  if not (buy and buy.BuyButton) or wheelBuy.buy then return end
  wheelBuy.buy = buy
  wheelBuy:SetScript("OnClick", function()
    if buy:IsVisible() and buy.BuyButton:IsEnabled() then buy.BuyButton:Click() end
  end)
  buy:HookScript("OnShow", function()
    if InCombatLockdown() then return end
    SetOverrideBindingClick(wheelBuy, true, "MOUSEWHEELUP", "FlipListsWheelBuy")
    SetOverrideBindingClick(wheelBuy, true, "MOUSEWHEELDOWN", "FlipListsWheelBuy")
  end)
  buy:HookScript("OnHide", function()
    if not InCombatLockdown() then ClearOverrideBindings(wheelBuy) end
  end)
  -- PBS never hears back when a gear buy fails (someone else got it first), so the button sits
  -- on "Buying..." for good. A buy that worked restarts the scan at 1s, so 2s means it failed.
  hooksecurefunc(buy, "BuyNow", function(self)
    C_Timer.After(2, function()
      if self:IsVisible() and self.BuyButton:GetText() == POINT_BLANK_SNIPER_L_BUYING then Restart() end
    end)
  end)
  hooksecurefunc(buy, "UpdateBuyState", function(self)
    if self.gotResult and not self.buyCommodity and self.BuyButton:GetText() == POINT_BLANK_SNIPER_L_SOLD then
      Restart()
    end
  end)
end
local wire = CreateFrame("Frame")
pcall(wire.RegisterEvent, wire, "AUCTION_HOUSE_SHOW")
wire:SetScript("OnEvent", function() C_Timer.After(0.5, WireBuyPanel) end)

-- /flips: the flip report in game. It keeps its own buy and sale log in FlipListsDB (AH mail
-- as you collect it, merchant sales as you make them), so it updates live and needs no TSM.
-- TSM's old log is copied in once, on the first login with this version.
local AH_CUT = 0.95  -- TSM logs the sale price before the 5% auction house cut

-- One-off import of TSM's log. keep maps a log source to the share of the price that reaches
-- you: AH sales lose the 5% cut, vendor sales do not. Rows from other sources are skipped.
local function ReadLog(key, keep)
  local out = {}
  local csv = TradeSkillMasterDB and TradeSkillMasterDB["r@Normal@internalData@" .. key]
  if type(csv) ~= "string" then return out end
  -- columns: itemString,stackSize,quantity,price,otherPlayer,player,time,source
  for line in csv:gmatch("[^\n]+") do
    local itemString, _, quantity, price, _, _, time, source = strsplit(",", line)
    local id, q, p, t = tonumber(itemString:match("^i:(%d+)")), tonumber(quantity), tonumber(price), tonumber(time)
    if id and q and p and t and keep[source] then
      out[id] = out[id] or {}
      tinsert(out[id], {t, q, p * keep[source]})
    end
  end
  return out
end

local function ByTime(a, b) return a[1] < b[1] end

-- A sale is a flip only against an earlier buy that is still unsold, oldest buy first.
-- Anything sold beyond that was looted or gathered while levelling, not flipped.
-- Returns units bought, units flipped, flip profit, looted sales value, units unsold, and what
-- those unsold units cost in total.
local function Match(buys, sales)
  table.sort(buys, ByTime)
  table.sort(sales, ByTime)
  local nBought, nSold, profit, looted, i = 0, 0, 0, 0, 1
  for _, b in ipairs(buys) do nBought = nBought + b[2] end
  local left = buys[1] and buys[1][2] or 0  -- units of buys[i] not matched yet
  for _, s in ipairs(sales) do
    local q = s[2]
    while q > 0 and buys[i] and buys[i][1] <= s[1] do
      local n = min(q, left)
      profit = profit + n * (s[3] - buys[i][3])
      nSold, q, left = nSold + n, q - n, left - n
      if left == 0 then
        i = i + 1
        left = buys[i] and buys[i][2] or 0
      end
    end
    looted = looted + q * s[3]
  end
  local unsoldCost = buys[i] and left * buys[i][3] or 0
  for j = i + 1, #buys do unsoldCost = unsoldCost + buys[j][2] * buys[j][3] end
  return nBought, nSold, profit, looted, nBought - nSold, unsoldCost
end

local function Money(copper)
  copper = floor(copper + 0.5)
  local text = GetMoneyString(abs(copper), true)
  return copper < 0 and ("|cffff5555-" .. text .. "|r") or text
end

-- Layout: one font string per cell, one row per item, faint stripes on every other row.
local COLS = {{"Item", 250, "LEFT"}, {"Bought", 70, "RIGHT"}, {"Sold", 70, "RIGHT"},
              {"Held", 70, "RIGHT"}, {"Profit", 120, "RIGHT"}}
local GAP, ROW_H, LEFT = 8, 18, 16
local WIDTH = GAP * (#COLS - 1)
for _, c in ipairs(COLS) do WIDTH = WIDTH + c[2] end

local function Cells(parent, y, font)
  local cells, x = {}, LEFT
  for i, c in ipairs(COLS) do
    local cell = parent:CreateFontString(nil, "OVERLAY", font)
    cell:SetPoint("TOPLEFT", x, y)
    cell:SetSize(c[2], ROW_H)
    cell:SetJustifyH(c[3])
    cell:SetWordWrap(false)  -- long names end in "..." instead of wrapping
    cells[i] = cell
    x = x + c[2] + GAP
  end
  return cells
end

-- The report on any frame: the /flips window or the AH tab. top is the y offset to start at.
-- buttonTopRight: the AH tab has free space right of the table, the /flips window does not.
local views = {}  -- every view made, so a new log row can refill the visible ones
local function MakeView(parent, top, maxRows, buttonTopRight)
  local view = {rows = {}, maxRows = maxRows}
  views[view] = true
  view.summary = parent:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  view.summary:SetPoint("TOPLEFT", LEFT, top)
  view.summary:SetJustifyH("LEFT")

  local headY = top - 30
  for i, cell in ipairs(Cells(parent, headY, "GameFontNormal")) do cell:SetText(COLS[i][1]) end
  local line = parent:CreateTexture(nil, "ARTWORK")
  line:SetColorTexture(1, 0.82, 0, 0.35)
  line:SetPoint("TOPLEFT", LEFT, headY - ROW_H - 1)
  line:SetSize(WIDTH, 1)

  for r = 1, maxRows do
    local y = headY - ROW_H - 4 - (r - 1) * ROW_H
    local row = {cells = Cells(parent, y, "GameFontHighlight")}
    -- Hovering a row shows the item's own tooltip, plus the best exit for held items
    row.hover = CreateFrame("Frame", nil, parent)
    row.hover:SetPoint("TOPLEFT", LEFT - 4, y)
    row.hover:SetSize(WIDTH + 8, ROW_H)
    row.hover:EnableMouse(true)
    row.hover:SetScript("OnEnter", function(self)
      if not row.item then return end
      local _, id, _, _, held, exit = unpack(row.item)
      GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
      GameTooltip:SetHyperlink("item:" .. id)
      if held > 0 and exit then
        GameTooltip:AddDoubleLine("All " .. held .. " held, at best exit", Money(held * exit), 1, 0.82, 0, 1, 1, 1)
      end
      GameTooltip:Show()
    end)
    row.hover:SetScript("OnLeave", function() GameTooltip:Hide() end)
    if r % 2 == 0 then
      row.stripe = parent:CreateTexture(nil, "ARTWORK")
      row.stripe:SetColorTexture(1, 1, 1, 0.04)
      row.stripe:SetPoint("TOPLEFT", LEFT - 4, y)
      row.stripe:SetSize(WIDTH + 8, ROW_H)
    end
    view.rows[r] = row
  end

  view.footer = parent:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  view.footer:SetPoint("TOPRIGHT", parent, "TOPLEFT", LEFT + WIDTH, headY - ROW_H - 10 - maxRows * ROW_H)
  view.footer:SetJustifyH("RIGHT")

  -- ReloadUI() is protected on Forever, but a secure button clicked by you may run /reload as
  -- macro text. Secure frames cannot be created in combat, so skip the button then.
  if not InCombatLockdown() then
    local reload = CreateFrame("Button", nil, parent, "SecureActionButtonTemplate, UIPanelButtonTemplate")
    reload:SetSize(140, 22)
    if buttonTopRight then
      reload:SetPoint("TOPRIGHT", parent, "TOPRIGHT", -16, top + 4)
    else
      reload:SetPoint("TOPLEFT", LEFT - 2, headY - ROW_H - 6 - maxRows * ROW_H)
    end
    reload:SetText("Refresh (/reload)")
    reload:SetAttribute("type", "macro")
    reload:SetAttribute("macrotext", "/reload")
    reload:RegisterForClicks("AnyUp", "AnyDown")
  end
  return view
end

local POISON = {}
for _, id in ipairs(POISONS) do POISON[id] = true end

-- Vendor price: from Lists.lua (Blizzard item API via ah_pull.py, covers every item seen on
-- the AH), else the game's item cache, which only knows items you have seen.
local function VendorPrice(id)
  local p = FlipLists_Vendor and FlipLists_Vendor[id] or select(11, C_Item.GetItemInfo(id))
  return p and p > 0 and p or nil
end

-- The most one held item can return: our own hourly EU house price after the AH cut
-- (FlipLists_Prices in Lists.lua, the lower of listed and sold at), or the vendor price if
-- that is more. Poisons cannot be vendored.
local function BestExit(id)
  local ah = FlipLists_Prices and FlipLists_Prices[id]
  ah = ah and floor(ah * AH_CUT)
  local vendor = not POISON[id] and VendorPrice(id) or nil
  if vendor and (not ah or vendor >= ah) then return vendor, "Vendor", ah, vendor end
  if ah then return ah, "AH", ah, vendor end
end

-- Without TSM, Point Blank Sniper still needs a price source for the Flip Vendor scan. It reads
-- the Oribos Exchange addon's OEMarketInfo(itemID, out) when that exists, so provide it (only if
-- the real addon is not installed): "OE Realm" = the vendor price, "OE Region" = our own EU price.
if not OEMarketInfo then
  function OEMarketInfo(itemID, out)
    out = out or {}
    local id = tonumber(itemID) or (type(itemID) == "string" and tonumber(itemID:match("item:(%d+)")))
    out.market = id and not POISON[id] and VendorPrice(id) or nil
    out.region = id and FlipLists_Prices and FlipLists_Prices[id]
    return out
  end
end

-- What you own of an item, not counting gear you wear or bags in your bag slots (bought to
-- use, not to flip): what sits inside your bags, plus the bank (GetItemCount with the bank
-- minus without, so worn copies cancel out), plus your live AH listings as last seen at the
-- AH (FlipListsDB.posted). An expired auction sitting in the mailbox is not counted.
local function BagCounts()
  local counts = {}
  for bag = 0, (NUM_BAG_SLOTS or 4) + 1 do  -- +1: the reagent bag, if there is one
    for slot = 1, C_Container.GetContainerNumSlots(bag) or 0 do
      local info = C_Container.GetContainerItemInfo(bag, slot)
      if info and info.itemID then counts[info.itemID] = (counts[info.itemID] or 0) + (info.stackCount or 1) end
    end
  end
  return counts
end

local function Owned(id, bags)
  local posted = FlipListsDB and FlipListsDB.posted and FlipListsDB.posted[id] or 0
  local bank = (C_Item.GetItemCount(id, true) or 0) - (C_Item.GetItemCount(id) or 0)
  return (bags[id] or 0) + bank + posted
end

-- Own log rows are {time, itemID, quantity, copper each}. Sales whose item could not be
-- resolved from the mail (id 0) can only be loot, so they go straight to the looted total.
local function ByItem(rows)
  local out, unknown = {}, 0
  for _, r in ipairs(rows or {}) do
    if r[2] and r[2] > 0 then
      out[r[2]] = out[r[2]] or {}
      tinsert(out[r[2]], {r[1], r[3], r[4]})
    else
      unknown = unknown + r[3] * r[4]
    end
  end
  return out, unknown
end

local waiting = {}  -- views showing "item 1234" for names the client has not loaded yet

local function Fill(view)
  waiting[view] = nil
  -- Bought on the AH, sold on the AH or to a vendor (the vendor-flip scan)
  local db = FlipListsDB or {}
  local bought = ByItem(db.buys)
  local sold, unknown = ByItem(db.sales)
  local items, total, gathered, stock = {}, 0, unknown, 0
  local bags = BagCounts()
  local ids = {}
  for id in pairs(bought) do ids[id] = true end
  for id in pairs(sold) do ids[id] = true end
  for id in pairs(ids) do
    local b, s, profit, looted, held = Match(bought[id] or {}, sold[id] or {})
    total, gathered = total + profit, gathered + looted
    -- Bought minus sold misses items opened, used, worn or destroyed: cap at what you own
    if held > 0 then held = min(held, Owned(id, bags)) end
    if s > 0 or held > 0 then
      local exit, via, ah, vendor = BestExit(id)
      if held > 0 and exit then stock = stock + held * exit end
      table.insert(items, {profit, id, b, s, held, exit, via, ah, vendor})
    end
  end
  -- Sold items first, best to worst, so a losing flip never drops off the bottom.
  -- Items not sold yet come after, and are the ones cut when rows run out.
  table.sort(items, function(a, b)
    if (a[4] > 0) ~= (b[4] > 0) then return a[4] > 0 end
    if a[1] ~= b[1] then return a[1] > b[1] end
    return a[2] < b[2]
  end)

  view.summary:SetText("|cffffd100Flip profit:|r " .. Money(total) ..
    "      |cffffd100Looted sales:|r " .. Money(gathered) ..
    "      |cffffd100Held stock worth:|r " .. Money(stock))
  for r, row in ipairs(view.rows) do
    local item = items[r]
    if item then
      local profit, id, b, s, held = unpack(item)
      -- Forever has no global GetItemInfo, only C_Item. Uncached names fill in on the next open.
      local name, _, quality = C_Item.GetItemInfo(id)
      if name and quality then
        name = "|c" .. select(4, C_Item.GetItemQualityColor(quality)) .. name .. "|r"
      end
      if not name then
        C_Item.RequestLoadItemDataByID(id)
        waiting[view] = true
      end
      local values = {name or ("item " .. id), b, s, held > 0 and held or "", s > 0 and Money(profit) or "-"}
      for i, cell in ipairs(row.cells) do cell:SetText(values[i]) end
    else
      for _, cell in ipairs(row.cells) do cell:SetText("") end
    end
    row.item = item
    row.hover:SetShown(item ~= nil)
    if row.stripe then row.stripe:SetShown(item ~= nil) end
  end
  local hidden = #items - view.maxRows
  local more = hidden > 0 and (hidden .. (hidden == 1 and " more item" or " more items") .. " not shown.  ") or ""
  view.footer:SetText(more .. "Live: AH sales count once you take the mail")
end

-- When item names arrive, refill any visible view that was waiting on them (once, 0.3s later,
-- since a fresh view triggers one event per missing item).
local names = CreateFrame("Frame")
pcall(names.RegisterEvent, names, "GET_ITEM_INFO_RECEIVED")
local pending
names:SetScript("OnEvent", function()
  if pending or not next(waiting) then return end
  pending = true
  C_Timer.After(0.3, function()
    pending = nil
    for v in pairs(waiting) do
      if v.summary:IsVisible() then Fill(v) end
    end
  end)
end)

-- "Best exit" on every item tooltip. Soulbound items cannot go on the AH, so they get the
-- vendor price only. TSM and Auctionator use the same hook on Forever.
if TooltipDataProcessor and Enum.TooltipDataType then
  TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, function(tooltip, data)
    if tooltip ~= GameTooltip and tooltip ~= ItemRefTooltip then return end
    local id = data and data.id
    if not id then return end
    local exit, via, _, vendor = BestExit(id)
    for _, line in ipairs(data.lines or {}) do
      if line.leftText == ITEM_SOULBOUND then exit, via = vendor, "Vendor" break end
    end
    if exit then tooltip:AddDoubleLine("Best exit", via .. " " .. Money(exit), 1, 0.82, 0, 1, 1, 1) end
  end)
end

local WINDOW_ROWS, TAB_ROWS = 16, 20
local report, view
local function Build()
  report = CreateFrame("Frame", "FlipListsFrame", UIParent, "BasicFrameTemplateWithInset")
  report:SetSize(WIDTH + LEFT * 2, 32 + 30 + ROW_H + 4 + WINDOW_ROWS * ROW_H + 34)
  report:SetPoint("CENTER")
  report:SetClampedToScreen(true)
  report:SetMovable(true)
  report:EnableMouse(true)
  report:RegisterForDrag("LeftButton")
  report:SetScript("OnDragStart", report.StartMoving)
  report:SetScript("OnDragStop", report.StopMovingOrSizing)
  tinsert(UISpecialFrames, "FlipListsFrame")  -- Escape closes it
  local title = report.TitleText
  if not title then
    title = report:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    title:SetPoint("TOP", 0, -5)
  end
  title:SetText("Flips")

  -- The template's Inset is a child frame drawn over the window's own text, so text goes on
  -- a child frame of its own, above the Inset.
  local content = CreateFrame("Frame", nil, report)
  content:SetAllPoints()
  content:SetFrameLevel(report:GetFrameLevel() + 10)

  view = MakeView(content, -34, WINDOW_ROWS)
end

local function ToggleFlips()
  if report and report:IsShown() then return report:Hide() end
  if not report then Build() end
  Fill(view)
  report:Show()
end

-- Export: addons cannot write files, so the ledger is shown as CSV in a text box, already
-- selected, for Ctrl+C. One row per buy or sale: copper each is after the 5% AH cut for sales.
local export
local function ExportCSV()
  local db = FlipListsDB or {}
  local lines = {"type,date,item id,item name,quantity,copper each"}
  for _, kind in ipairs({"buys", "sales"}) do
    for _, r in ipairs(db[kind] or {}) do
      local name = (C_Item.GetItemInfo(r[2]) or ""):gsub('"', '""')
      tinsert(lines, format('%s,%s,%d,"%s",%d,%d', kind == "buys" and "buy" or "sale",
        date("%Y-%m-%d %H:%M", r[1]), r[2], name, r[3], r[4]))
    end
  end
  if not export then
    export = CreateFrame("Frame", "FlipListsExportFrame", UIParent, "BasicFrameTemplateWithInset")
    export:SetSize(620, 420)
    export:SetPoint("CENTER")
    export:SetFrameStrata("DIALOG")
    export:SetMovable(true)
    export:EnableMouse(true)
    export:RegisterForDrag("LeftButton")
    export:SetScript("OnDragStart", export.StartMoving)
    export:SetScript("OnDragStop", export.StopMovingOrSizing)
    tinsert(UISpecialFrames, "FlipListsExportFrame")
    export.title = export:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    export.title:SetPoint("TOP", 0, -5)
    local scroll = CreateFrame("ScrollFrame", nil, export, "UIPanelScrollFrameTemplate")
    scroll:SetPoint("TOPLEFT", 12, -30)
    scroll:SetPoint("BOTTOMRIGHT", -32, 12)
    export.box = CreateFrame("EditBox", nil, scroll)
    export.box:SetMultiLine(true)
    export.box:SetFontObject(ChatFontNormal)
    export.box:SetWidth(570)
    export.box:SetAutoFocus(false)
    export.box:SetScript("OnEscapePressed", function() export:Hide() end)
    scroll:SetScrollChild(export.box)
  end
  export.title:SetText("Flips export: " .. (#lines - 1) .. " rows. Ctrl+C to copy, paste into a spreadsheet")
  export.box:SetText(table.concat(lines, "\n"))
  export:Show()
  export.box:SetFocus()
  export.box:HighlightText()
end

SLASH_FLIPLISTS1 = "/flips"
SlashCmdList.FLIPLISTS = function(msg)
  if (msg or ""):lower():match("^%s*export") then return ExportCSV() end
  ToggleFlips()
end

-- Minimap button: click opens Flips, drag moves it around the minimap ring. Its angle and
-- whether it is hidden are saved in FlipListsDB.minimap.
local mini
local function MiniPlace()
  local a = math.rad(FlipListsDB.minimap.angle or 200)
  local r = Minimap:GetWidth() / 2 + 6
  mini:ClearAllPoints()
  mini:SetPoint("CENTER", Minimap, "CENTER", math.cos(a) * r, math.sin(a) * r)
end
local function MiniButton()
  FlipListsDB.minimap = FlipListsDB.minimap or {}
  if mini then return mini:SetShown(not FlipListsDB.minimap.hide) end
  mini = CreateFrame("Button", "FlipListsMinimapButton", Minimap)
  mini:SetSize(31, 31)
  mini:SetFrameStrata("MEDIUM")
  mini:SetFrameLevel(8)
  mini:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")
  local icon = mini:CreateTexture(nil, "BACKGROUND")
  icon:SetTexture("Interface\\Icons\\INV_Misc_Coin_02")
  icon:SetSize(20, 20)
  icon:SetPoint("TOPLEFT", 7, -5)
  local border = mini:CreateTexture(nil, "OVERLAY")
  border:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder")
  border:SetSize(53, 53)
  border:SetPoint("TOPLEFT")
  mini:RegisterForClicks("LeftButtonUp", "RightButtonUp")
  mini:RegisterForDrag("LeftButton")
  mini:SetScript("OnClick", function(_, button)
    if button == "RightButton" then ExportCSV() else ToggleFlips() end
  end)
  mini:SetScript("OnDragStart", function(self)
    self:SetScript("OnUpdate", function()
      local mx, my = Minimap:GetCenter()
      local x, y = GetCursorPosition()
      local scale = Minimap:GetEffectiveScale()
      FlipListsDB.minimap.angle = math.deg(math.atan2(y / scale - my, x / scale - mx))
      MiniPlace()
    end)
  end)
  mini:SetScript("OnDragStop", function(self) self:SetScript("OnUpdate", nil) end)
  mini:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_LEFT")
    GameTooltip:AddLine("Flip Lists")
    GameTooltip:AddLine("Click: Flips. Right-click: export. Drag: move.", 1, 1, 1)
    GameTooltip:Show()
  end)
  mini:SetScript("OnLeave", GameTooltip_Hide)
  MiniPlace()
  mini:SetShown(not FlipListsDB.minimap.hide)
end

-- Settings panel (Esc > Options > AddOns > Flip Lists): minimap button on/off and export.
local function SettingsPanel()
  local panel = CreateFrame("Frame")
  panel.name = "Flip Lists"
  local title = panel:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
  title:SetPoint("TOPLEFT", 16, -16)
  title:SetText("Flip Lists")
  local show = CreateFrame("CheckButton", nil, panel, "UICheckButtonTemplate")
  show:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -12)
  show.Text = show.Text or show:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
  show.Text:SetPoint("LEFT", show, "RIGHT", 4, 0)
  show.Text:SetText("Show the minimap button")
  show:SetScript("OnShow", function(self) self:SetChecked(not FlipListsDB.minimap.hide) end)
  show:SetScript("OnClick", function(self)
    FlipListsDB.minimap.hide = not self:GetChecked()
    MiniButton()
  end)
  local btn = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
  btn:SetPoint("TOPLEFT", show, "BOTTOMLEFT", 0, -16)
  btn:SetSize(200, 24)
  btn:SetText("Export Flips (CSV)")
  btn:SetScript("OnClick", ExportCSV)
  local hint = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  hint:SetPoint("TOPLEFT", btn, "BOTTOMLEFT", 0, -8)
  hint:SetText("Every buy and sale in your Flips ledger. Also: /flips export")
  -- Realm type, one tickbox each (only one stays ticked). Saved per character, applied at once.
  local rs = panel:CreateFontString(nil, "ARTWORK", "GameFontNormal")
  rs:SetPoint("TOPLEFT", hint, "BOTTOMLEFT", 0, -24)
  rs:SetText("Realm type for this character (your faction is picked for you)")
  local boxes, prev = {}, rs
  for _, name in ipairs(RULESETS) do
    local b = CreateFrame("CheckButton", nil, panel, "UICheckButtonTemplate")
    b:SetPoint("TOPLEFT", prev, "BOTTOMLEFT", 0, prev == rs and -8 or 0)
    b.Text = b.Text or b:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    b.Text:SetPoint("LEFT", b, "RIGHT", 4, 0)
    b.Text:SetText(name)
    b:SetScript("OnShow", function(self) self:SetChecked((FlipListsCharDB.ruleset or "Normal") == name) end)
    b:SetScript("OnClick", function(self)
      for _, o in ipairs(boxes) do o:SetChecked(o == self) end
      FlipListsCharDB.ruleset = name
      LoadLists()
    end)
    table.insert(boxes, b)
    prev = b
  end
  local note = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  note:SetPoint("TOPLEFT", prev, "BOTTOMLEFT", 0, -8)
  note:SetText("Picks which auction house the snipe caps and prices come from. Rebuilds the lists straight away.")
  if Settings and Settings.RegisterCanvasLayoutCategory then
    Settings.RegisterAddOnCategory(Settings.RegisterCanvasLayoutCategory(panel, panel.name))
  elseif InterfaceOptions_AddCategory then
    InterfaceOptions_AddCategory(panel)
  end
end

local ui = CreateFrame("Frame")
ui:RegisterEvent("PLAYER_LOGIN")
ui:SetScript("OnEvent", function()
  FlipListsDB = FlipListsDB or {}
  MiniButton()
  SettingsPanel()
end)

-- A "Flips" tab in the auction house, after Sniping (tabOrder 6). Auctionator builds its tabs
-- when the AH first opens, from this list sorted by tabOrder. TSM adds its own tab after them.
-- The frame comes from FlipListsTabTemplate in Tab.xml, which calls these two on load and show.
function FlipListsTab_OnLoad(self) self.view = MakeView(self, -14, TAB_ROWS, true) end
function FlipListsTab_OnShow(self) Fill(self.view) end

-- Seven addon tabs at LibAHTab's 20px text padding run past the right edge of the AH frame.
-- Every addon (Auctionator, Point Blank Sniper, TSM, this one) shares the newest LibAHTab, so
-- its tab list holds them all. Tighten their padding each time the AH opens.
local tighten = CreateFrame("Frame")
pcall(tighten.RegisterEvent, tighten, "AUCTION_HOUSE_SHOW")
tighten:SetScript("OnEvent", function()
  C_Timer.After(0.2, function()
    local lib = LibStub and LibStub("LibAHTab-1-0", true)
    local state = lib and lib.internalState
    if not state then return end
    for _, tab in ipairs(state.Tabs) do PanelTemplates_TabResize(tab, 4, nil, 50) end
  end)
end)
-- A "Flips" chat tab: every Point Blank Sniper buy, with why you bought it (the list you were
-- scanning) and its best exit, plus AH sales. Chat tabs forget on /reload, so the last 60
-- lines are saved in FlipListsDB and shown again, greyed, after each login or /reload.
local LOG_KEEP = 60
local logFrame, pendingBuy

local function FindLogTab()
  for i = 1, NUM_CHAT_WINDOWS or 10 do
    if GetChatWindowInfo(i) == "Flips" then return _G["ChatFrame" .. i] end
  end
end

local function Log(text)
  local line = date("%d %b %H:%M") .. "  " .. text
  table.insert(FlipListsDB.log, line)
  while #FlipListsDB.log > LOG_KEEP do table.remove(FlipListsDB.log, 1) end
  if logFrame then logFrame:AddMessage(line) end
end

local logStart = CreateFrame("Frame")
logStart:RegisterEvent("PLAYER_LOGIN")
logStart:SetScript("OnEvent", function()
  FlipListsDB = FlipListsDB or {}  -- saved variables are loaded by now
  FlipListsDB.log = FlipListsDB.log or {}
  C_Timer.After(2, function()
    if not FindLogTab() then FCF_OpenNewWindow("Flips", true) end  -- true: no default channels
    logFrame = FindLogTab()
    if not logFrame then return end
    for _, line in ipairs(FlipListsDB.log) do logFrame:AddMessage("|cff999999" .. line .. "|r") end
  end)
end)

-- Point Blank Sniper's Buy button only starts a purchase, so note it here and log it when
-- the purchase succeeds. Hooking the mixin works because PBS copies it into its buy frame
-- when the AH first opens, after this file has loaded.
if PointBlankSniperBuyFrameMixin then
  hooksecurefunc(PointBlankSniperBuyFrameMixin, "BuyNow", function(self)
    local r, key = self.resultInfo, self.expectedItemKey
    if not (r and key) then return end
    local qty = self.ghostCount or r.quantity or 1
    local each = self.info.isCommodity and r.unitPrice or (r.buyoutAmount or 0) / math.max(qty, 1)
    local list = PointBlankSniper.Config.Get(PointBlankSniper.Config.Options.CURRENT_LIST)
    pendingBuy = {id = key.itemID, qty = qty, each = each, list = list}
  end)
end

local function LogBuy(b)
  local name, link = C_Item.GetItemInfo(b.id)
  local exit, via = BestExit(b.id)
  local why = b.list == "Flip Vendor" and "|cffffd100for a VENDOR|r, sell it to any merchant"
    or ("|cffffd100to RESELL on the AH|r (" .. tostring(b.list) .. ")")
  local plan = exit and (". Best exit " .. via .. " " .. Money(exit) .. " each") or ""
  local warn = exit and exit < b.each and " |cffff5555(less than you paid)|r" or ""
  Log("Bought " .. b.qty .. "x " .. (link or name or ("item " .. b.id)) .. " at " .. Money(b.each) ..
    " each, " .. why .. plan .. warn)
end

local soldPrefix = ERR_AUCTION_SOLD_S and ERR_AUCTION_SOLD_S:match("^(.-)%%s")
local logEvents = CreateFrame("Frame")
for _, event in ipairs({"COMMODITY_PURCHASE_SUCCEEDED", "AUCTION_HOUSE_PURCHASE_COMPLETED", "CHAT_MSG_SYSTEM"}) do
  pcall(logEvents.RegisterEvent, logEvents, event)
end
logEvents:SetScript("OnEvent", function(_, event, msg)
  if not FlipListsDB then return end
  if event == "CHAT_MSG_SYSTEM" then
    if soldPrefix and type(msg) == "string" and msg:sub(1, #soldPrefix) == soldPrefix then
      Log("|cff00ff00Sold on the AH:|r " .. msg:sub(#soldPrefix + 1):gsub("%.$", ""))
    end
  elseif pendingBuy then
    LogBuy(pendingBuy)
    pendingBuy = nil
  end
end)

-- Auctionator's Selling tab fills in the cheapest listing minus your undercut. Two fixes on top,
-- applied after it fills the price in (you still press Post yourself):
-- 1. Thin listings: a few cheap units at the bottom sell in minutes, so when the cheapest rows
--    hold fewer units between them than you are posting (at least THIN), undercut the first
--    row past them instead.
-- 2. Dumps: someone selling cheap is what a snipe buys from, so do not follow them down. Rows
--    under MARKET (80%) of your own market price (FlipLists_Prices, the lower of listed and sold
--    at over 7 days) are skipped, and the price never goes under that line. Seen 2026-11-22:
--    crates sold at 3s56 into a dump while they sell at 14s80.
-- 3. Floor: never below break-even on what the unsold units cost you (after the 5% cut), or
--    below what a merchant would pay. Gear gets the floor only (every listing is one item).
-- Each change is noted in the Flips chat tab (not saved), so you can always type over it.
local THIN = 20
local MARKET = 0.8

local function PriceNote(text)
  local frame = logFrame or DEFAULT_CHAT_FRAME
  frame:AddMessage("|cff33ff99Price:|r " .. text)
end

local function PriceFloor(id)
  local low, why = 0, nil
  local db = FlipListsDB
  local buys = db and ByItem(db.buys)[id]
  if buys then
    local _, _, _, _, unsold, cost = Match(buys, ByItem(db.sales)[id] or {})
    if unsold > 0 then
      low, why = math.ceil(cost / unsold / AH_CUT), "break-even on the " .. unsold .. " you bought at " .. Money(cost / unsold) .. " each"
    end
  end
  local vendor = not POISON[id] and VendorPrice(id)
  if vendor and math.ceil(vendor / AH_CUT) > low then
    low, why = math.ceil(vendor / AH_CUT), "a merchant pays " .. Money(vendor)
  end
  return low, why
end

local lastNote, lastNoteAt = nil, 0
local function ApplyFloor(self, id, price, notes)
  local low, why = PriceFloor(id)
  if price < low then
    price = low
    tinsert(notes, "raised to " .. Money(low) .. ", " .. why)
  end
  if price ~= self.Price:GetAmount() then self:UpdateSalesPrice(price) end
  local _, link = C_Item.GetItemInfo(id)
  local note = #notes > 0 and ((link or ("item " .. id)) .. " at " .. Money(price) .. ": " .. table.concat(notes, ", "))
  if note and (note ~= lastNote or GetTime() - lastNoteAt > 5) then  -- several triggers, one note
    lastNote, lastNoteAt = note, GetTime()
    PriceNote(note)
  end
end

-- Price a commodity straight from the search rows. Auctionator does not always run its own
-- pricing on Forever (seen 2026-11-23: Linen kept its stored 19c with 15,665 listed from 30c),
-- so this runs on every results update, whatever Auctionator did.
local function PriceCommodity(self, itemID)
  local n = C_AuctionHouse.GetNumCommoditySearchResults(itemID) or 0
  local price = self.Price:GetAmount()
  local notes, ahead, base = {}, 0, nil
  local thin = max(THIN, self.Quantity and self.Quantity:GetNumber() or 0)
  local market = FlipLists_Prices and FlipLists_Prices[itemID]
  local mfloor, dumped, first = market and math.ceil(market * MARKET) or 0, 0, nil
  for i = 1, n do
    local r = C_AuctionHouse.GetCommoditySearchResultInfo(itemID, i)
    if not r then break end
    if r.unitPrice < mfloor then
      dumped = dumped + r.quantity
    elseif r.containsOwnerItem then  -- never jump past your own listing: sit at its price
      base = r.unitPrice
      if ahead > 0 then tinsert(notes, "skipped " .. ahead .. " cheaper (thin), matched your own listing") end
      break
    elseif ahead + r.quantity >= thin then
      base = Auctionator.Selling.CalculateItemPriceFromPrice(r.unitPrice)
      if ahead > 0 then tinsert(notes, "skipped " .. ahead .. " cheaper (thin), undercut " .. r.quantity .. " at " .. Money(r.unitPrice)) end
      break
    else
      first = first or r.unitPrice
      ahead = ahead + r.quantity
    end
  end
  if not base and first then  -- every row is thin: plain undercut of the cheapest above the dump
    base = Auctionator.Selling.CalculateItemPriceFromPrice(first)
  end
  if dumped > 0 then
    tinsert(notes, "skipped " .. dumped .. " under 80% of market " .. Money(market))
    base = max(base or mfloor, mfloor)
  end
  price = base or price
  if price and price > 0 then ApplyFloor(self, itemID, price, notes) end
end

local function SaleItem()
  local f = AuctionatorSellingFrame and AuctionatorSellingFrame.SaleItemFrame
  return f and f:IsVisible() and f.expectedItemKey and f
end

if AuctionatorSaleItemMixin then
  hooksecurefunc(AuctionatorSaleItemMixin, "ProcessCommodityResults", function(self, itemID)
    if itemID then PriceCommodity(self, itemID) end
  end)
  hooksecurefunc(AuctionatorSaleItemMixin, "ProcessItemResults", function(self, itemKey)
    local price = self.Price and self.Price:GetAmount()
    if itemKey and itemKey.itemID and price and price > 0 then ApplyFloor(self, itemKey.itemID, price, {}) end
  end)
  -- After a search starts, check every 0.3s (up to 3s) until its rows are in, then price once.
  hooksecurefunc(AuctionatorSaleItemMixin, "DoSearch", function(self)
    local key, tries = self.expectedItemKey, 0
    local function Try()
      if not key or self.expectedItemKey ~= key then return end  -- another item was picked
      tries = tries + 1
      if (C_AuctionHouse.GetNumCommoditySearchResults(key.itemID) or 0) > 0 then
        PriceCommodity(self, key.itemID)
      elseif tries < 10 then
        C_Timer.After(0.3, Try)
      end
    end
    C_Timer.After(0.3, Try)
  end)
  local results = CreateFrame("Frame")
  results:RegisterEvent("COMMODITY_SEARCH_RESULTS_UPDATED")
  results:SetScript("OnEvent", function(_, _, itemID)
    local f = SaleItem()
    if f and f.expectedItemKey.itemID == itemID then PriceCommodity(f, itemID) end
  end)
end

-- Flips' own buy and sale log: FlipListsDB.buys and .sales, rows {time, itemID, qty, copper
-- each}. AH buys and sales both arrive as mail, so they are recorded as you take the mail,
-- the same way TSM does it. Merchant sales are recorded as you sell.
local function Changed()
  for v in pairs(views) do
    if v.summary:IsVisible() then Fill(v) end
  end
end

local function Record(kind, id, qty, each)
  if not (FlipListsDB and FlipListsDB[kind] and qty and qty > 0 and each) then return end
  tinsert(FlipListsDB[kind], {time(), id or 0, qty, floor(each + 0.5)})
  Changed()
end

-- A sale mail only names the item. Items in your bags resolve directly, anything else you
-- bought is found among your buys. What is left is loot, which needs no item ID.
local function IdByName(name)
  local id = C_Item.GetItemInfoInstant(name)
  if id then return id end
  for _, r in ipairs(FlipListsDB.buys) do
    if r[2] > 0 and C_Item.GetItemInfo(r[2]) == name then return r[2] end
  end
  for id in pairs(FlipListsDB.posted or {}) do
    if C_Item.GetItemInfo(id) == name then return id end
  end
end

local function FreeSlots()
  local free = 0
  for bag = 0, NUM_BAG_SLOTS or 4 do free = free + (C_Container.GetContainerNumFreeSlots(bag) or 0) end
  return free
end

-- Runs just before the mail is taken. Money already taken (0) or an attachment already
-- gone means the mail was recorded before. With full bags a buy is not taken, so skip it.
-- Each mail is recorded once, per attachment, at the purchase's real unit price. A buy bigger
-- than the item's stack size arrives split over several attachments (24 Linen = 20 + 4), and
-- the same mail can be taken by more than one call. A mail is known by its subject, arrival
-- (daysLeft) and invoice, which stay fixed while it sits in the inbox.
local seenMail = {}
local function NoteMail(index, attachment)
  if not FlipListsDB then return end
  local kind, itemName, _, bid, _, _, ahcut, _, _, _, count = GetInboxInvoiceInfo(index)
  if not (kind and bid) then return end
  local _, _, _, subject, money, _, daysLeft = GetInboxHeaderInfo(index)
  local key = table.concat({tostring(subject), tostring(daysLeft), kind, tostring(itemName), bid}, "|")
  local seen = seenMail[key] or {}
  seenMail[key] = seen
  if kind == "seller" then
    if itemName and money and money > 0 and not seen.money then
      seen.money = true
      count = count or 1
      Record("sales", IdByName(itemName), count, (bid - (ahcut or 0)) / count)
    end
  elseif kind == "buyer" and attachment ~= "money" then
    local slots = ATTACHMENTS_MAX_RECEIVE or 16
    if not seen.unit then  -- first look, while every attachment is still there
      local total = 0
      for a = 1, slots do total = total + (select(4, GetInboxItem(index, a)) or 0) end
      seen.unit = bid / max(count or total, 1)
    end
    local free = FreeSlots()
    for a = attachment or 1, attachment or slots do
      local link = GetInboxItemLink(index, a)
      local id = link and tonumber(link:match("item:(%d+)"))
      local n = select(4, GetInboxItem(index, a))
      if id and n and n > 0 and not seen[a] and free > 0 then
        seen[a], free = true, free - 1
        Record("buys", id, n, seen.unit)
      end
    end
  end
end

local function Wrap(name, attachmentOf)
  local orig = _G[name]
  if not orig then return end
  _G[name] = function(index, ...)
    pcall(NoteMail, index, attachmentOf(...))
    return orig(index, ...)
  end
end
Wrap("TakeInboxMoney", function() return "money" end)
Wrap("TakeInboxItem", function(attachment) return attachment end)
Wrap("AutoLootMailItem", function() return nil end)

-- Selling to a merchant: the item is still in its slot (locked) until the server replies.
if C_Container.UseContainerItem then
  hooksecurefunc(C_Container, "UseContainerItem", function(bag, slot)
    if not (FlipListsDB and MerchantFrame and MerchantFrame:IsShown()) then return end
    local info = C_Container.GetContainerItemInfo(bag, slot)
    if not (info and info.itemID) or info.hasNoValue or POISON[info.itemID] then return end
    local price = select(11, C_Item.GetItemInfo(info.itemID))
    if price and price > 0 then Record("sales", info.itemID, info.stackCount or 1, price) end
  end)
end

-- Buying back costs what the merchant paid, so it undoes that sale: drop the newest sale row
-- for the same item and stack size. Read before the call, while the buyback slot still holds it.
if BuybackItem then
  local orig = BuybackItem
  BuybackItem = function(index, ...)
    pcall(function()
      local link = GetBuybackItemLink(index)
      local id = link and tonumber(link:match("item:(%d+)"))
      local qty = select(4, GetBuybackItemInfo(index))
      local sales = FlipListsDB and FlipListsDB.sales
      if not (id and sales) then return end
      for i = #sales, 1, -1 do
        if sales[i][2] == id and sales[i][3] == qty then
          table.remove(sales, i)
          Changed()
          return
        end
      end
    end)
    return orig(index, ...)
  end
end

-- Your live listings, for Held: saved whenever the AH lists them (Auctions or Selling tab).
local ledger = CreateFrame("Frame")
ledger:RegisterEvent("PLAYER_LOGIN")
pcall(ledger.RegisterEvent, ledger, "OWNED_AUCTIONS_UPDATED")
-- A sale, buyback or mail is logged before the item moves, so refill again once bags settle
pcall(ledger.RegisterEvent, ledger, "BAG_UPDATE_DELAYED")
ledger:SetScript("OnEvent", function(_, event)
  if event == "BAG_UPDATE_DELAYED" then return Changed() end
  FlipListsDB = FlipListsDB or {}
  if event == "OWNED_AUCTIONS_UPDATED" then
    local posted, active = {}, Enum.AuctionStatus and Enum.AuctionStatus.Active or 0
    for _, a in ipairs(C_AuctionHouse.GetOwnedAuctions() or {}) do
      local id = a.itemKey and a.itemKey.itemID
      if id and a.status == active then posted[id] = (posted[id] or 0) + (a.quantity or 1) end
    end
    FlipListsDB.posted = posted
    -- A sale mail only names the item, and the name lookup fails for gear the game has not
    -- cached (seen 2026-11-24: 4 gear sales saved as item 0). Load every listed item now.
    for id in pairs(posted) do C_Item.RequestLoadItemDataByID(id) end
    Changed()
    return
  end
  FlipListsDB.buys = FlipListsDB.buys or {}
  FlipListsDB.sales = FlipListsDB.sales or {}
  if FlipListsDB.imported or not TradeSkillMasterDB then return end
  local function Copy(into, byItem)
    for id, rows in pairs(byItem) do
      for _, r in ipairs(rows) do tinsert(into, {r[1], id, r[2], floor(r[3] + 0.5)}) end
    end
  end
  Copy(FlipListsDB.buys, ReadLog("csvBuys", {Auction = 1}))
  Copy(FlipListsDB.sales, ReadLog("csvSales", {Auction = AH_CUT, Vendor = 1}))
  FlipListsDB.imported = time()
  print("|cff00ff00Flip Lists:|r copied TSM's log into Flips: " .. #FlipListsDB.buys .. " buys, " ..
    #FlipListsDB.sales .. " sales. From now on Flips keeps its own log.")
end)

if Auctionator.Tabs and Auctionator.Tabs.Register then
  Auctionator.Tabs.Register({
    name = "FlipListsFlips",
    textLabel = "Flips",
    tabTemplate = "FlipListsTabTemplate",
    tabHeader = "Flips",
    tabFrameName = "FlipListsTabFrame",
    tabOrder = 7,
  })
end
"""

# Same anchors as Point Blank Sniper's tab frame, so it sits in the same space.
TAB_XML = """<Ui xmlns="http://www.blizzard.com/wow/ui/">
  <Frame name="FlipListsTabTemplate" virtual="true" hidden="true">
    <Anchors>
      <Anchor point="TOP" y="-60"/>
      <Anchor point="LEFT" x="4"/>
      <Anchor point="BOTTOMRIGHT" x="-4"/>
    </Anchors>
    <Scripts>
      <OnLoad function="FlipListsTab_OnLoad"/>
      <OnShow function="FlipListsTab_OnShow"/>
    </Scripts>
  </Frame>
</Ui>
"""


MIN_SALE_HOURS = 24  # hours of sales estimates from ah_pull.py before its prices are trusted


def cap_skewed(items, data, source, where):
    """Point Blank Sniper uses a term's max price instead of its price source. Once ah_pull.py
    has a day of sales estimates, every item it has seen sell gets a max price of 70% of the
    lowest of its sold-at price, its typical listing price (sold-at counts cancels too, so it
    can read high) and the cheapest listing in the latest pull (both 24h figures lag a falling
    market). Items with no sales yet keep no max price, so PBS uses its price source."""
    own = data["items"] if data and data["sale_hours"] >= MIN_SALE_HOURS else {}
    if data and not own:
        print(f"    {where}: {data['sale_hours']} of {MIN_SALE_HOURS} hours of sales so far, no caps yet")
    out, mine = [], 0
    for term in items:
        ids = item_ids(term.strip('"'))
        seen = [i for i in ids if i in own and own[i][1]]
        if seen:
            listed, sold_at, now, _ = own[max(seen, key=lambda i: own[i][3])]
            low = min(p for p in (listed, sold_at, now) if p)  # now is 0 with nothing listed
            out.append(f"{term};;;;;;;;;{low * 0.7 / 10000:.4f}")
            mine += 1
        else:
            out.append(term)
    if own:
        print(f"    {where}: {mine} of {len(items)} max prices from own AH data ({source}, {data['sale_hours']} hours of sales)")
    return out


def main():
    lists = {}
    for line in SOURCE.read_text().splitlines():
        if "^" in line:
            name, *items = line.split("^")
            lists[name] = items
    # json.dumps gives a valid Lua string literal for these ASCII names
    terms = lambda items: ", ".join(json.dumps(i) for i in items)
    body = "".join(f"  [{json.dumps(n)}] = {{{terms(items)}}},\n" for n, items in lists.items())
    # Per house: Flip Snipe with that house's max prices, and its own price per item for Best exit
    # and the selling floor: the lower of listed and sold at, since sold at counts cancelled
    # pricey listings and can read 10x high. Houses with no data yet are left out (no caps).
    houses = ""
    for house, where in HOUSES.items():
        data, source = load_summary(house)
        if not data:
            continue
        own = {i: int(min(v[0], v[1]) if v[0] else v[1]) for i, v in data["items"].items() if v[1]}
        houses += (f"  [{house}] = {{updated = {int(data['updated'])},\n"
                   f"    snipe = {{{terms(cap_skewed(lists['Flip Snipe'], data, source, where))}}},\n"
                   f"    prices = {{{''.join(f'[{i}]={p},' for i, p in sorted(own.items()))}}}}},\n")
    ADDON.mkdir(parents=True, exist_ok=True)
    (ADDON / "FlipLists.toc").write_text(TOC)
    (ADDON / "FlipLists.lua").write_text(MAIN)
    (ADDON / "Tab.xml").write_text(TAB_XML)
    # Vendor prices for the Flip Vendor scan and Best exit, so they work for uncached items too
    with sqlite3.connect(db_path(DEFAULT)) as db:
        vendor = db.execute("SELECT item, price FROM vendor WHERE price > 0 ORDER BY item").fetchall()
    vendor_body = "".join(f"[{i}]={p}," for i, p in vendor)
    (ADDON / "Lists.lua").write_text("FlipLists_Data = {\n" + body + "}\nFlipLists_Houses = {\n" + houses +
                                       "}\nFlipLists_Vendor = {" + vendor_body + "}\n")
    for n, items in lists.items():
        print(f"  {n}: {len(items)} items")
    print(f"Written to {ADDON}. In game: /reload")


if __name__ == "__main__":
    main()
