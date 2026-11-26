# FlipLists

Ok, this started as a way to stop guessing what to pay on the WoW Forever auction house and, it kinda grew from there.

FlipLists sits on top of Auctionator and Point Blank Sniper. It loads the shopping lists for you, sets a safe max price on every item (from REAL auction house data, pulled every hour), helps price what you sell, and keeps a ledger of every flip so you can see what actually made money.

It doesnt buy anything for you. You still press Buy and you still press Post, it just makes sure the numbers in front of you are sensible.

> EU WoW Forever only. Every realm type has its own auction house per faction, so pick your realm type once in the settings (see below).

## What you need

- WoW Forever (EU)
- [Auctionator](https://www.curseforge.com/wow/addons/auctionator)
- [Point Blank Sniper](https://www.curseforge.com/wow/addons/point-blank-sniper) (optional, but the snipe side needs it)
- [WowUp](https://wowup.io) to install and update it (you can also grab the zip from Releases)
- To know your realm type: Normal, PvP, RP or RP-PvP (it's shown next to the realm name on the realm list)

## Installing it

1. Open WowUp and pick your Forever install
2. Go to Get Addons, then Install from URL
3. Paste `https://github.com/darthvader666uk/wow-forever-flips` and press Install
4. In game, type `/reload` (or log in)
5. Pick your realm type (below), once per character

You should see this in chat:

```
Flip Lists: updated Flip Herbs (35), Flip Skinning (39), Flip Snipe (81), Flip Vendor (1), Normal Alliance AH data from 14:22
```

The end tells you which auction house the prices are from and when they were pulled. A new release goes out every 3 hours, so let WowUp update it and `/reload` to pick up the new prices (addons cant re-read their files without a reload).

## Picking your realm type

Forever has a separate auction house for each realm type and faction, and the prices can be quite different between them. Your faction is picked for you, but the game doesnt tell addons what type of realm you're on (I checked, the realm name comes back blank on Forever), so you pick it once:

1. Esc → Options → AddOns → Flip Lists
2. Tick your realm type: Normal, PvP, RP or RP-PvP

It's saved per character and the lists rebuild straight away, no reload needed. Until you pick one it uses Normal and says so in chat on every login.

| Realm type | Alliance house | Horde house |
|---|---|---|
| Normal | 111 | 114 |
| PvP | 110 | 113 |
| RP | 119 | 120 |
| RP-PvP | 123 | 124 |

(Blackwater, the neutral goblin auction house, isnt covered.)

The Normal Alliance house has the longest history (that's mine). The others were added on 24 Nov 2026, so their max prices kick in after a day of data and the selling checks after a couple of hours. Until then, Point Blank Sniper has nothing to compare against on those houses and wont flag anything as a snipe.

## SO this is how it works

Every hour a GitHub Action pulls all 8 Forever auction houses from the Blizzard API, keeps 7 days of it, and works out three prices per item:

- **Listed:** the typical listing price over the week
- **Sold at:** what it actually sold for (worked out from listings that disappear between pulls)
- **Now:** the cheapest listing in the latest pull

Then it builds the addon with every house's prices baked in (the addon only uses yours) and publishes it as a release every 3 hours (or on the next pull after a code change). Caps that are 3 hours old cost almost nothing: replaying a day of my house's data, they flagged a few extra items that were still well under the selling floor and missed about 4c worth. That's it, no app running on your PC and no TSM.

## The shopping lists

Four lists are added to Auctionator, and replaced on every login (so dont edit them in game, they get overwritten):

| List | What it's for |
|---|---|
| Flip Snipe | 81 items that sell fast and dip often, each with a max price |
| Flip Vendor | One blank search that matches EVERY item, for buying things below what a merchant pays |
| Flip Herbs | Herbs |
| Flip Skinning | Leather, hides and scales |

The max price on Flip Snipe is **70% of the lowest of listed, sold at and now**. Taking the lowest of the three means a falling market doesnt catch you out (sold at can read high because cancelled listings look like sales).

Worked example, Iron Bar:
- Market price 3s 61c, so the max is 70% of that = 2s 53c
- Point Blank Sniper found 20 at 2s 40c, so I bought them
- Posted at 3s 59c, which is 3s 41c each after the 5% AH cut
- About 1s profit per bar, 20s on the lot

## Point Blank Sniper setup

FlipLists gives Point Blank Sniper two price sources (they show up as Oribos Exchange, only if you dont have the real Oribos Exchange addon installed):

- **Region - Oribos Exchange** = the price on your own auction house
- **Realm - Oribos Exchange** = what a merchant pays for it

The settings I use:

| Scan | Shopping List | Price Source | Percentage | Scan mode |
|---|---|---|---|---|
| Snipe | Flip Snipe | Region - Oribos Exchange | 70 | Keys |
| Vendor | Flip Vendor | Realm - Oribos Exchange | 90 | Blank |

Keys is MUCH faster for the snipe list (a round takes under a second, Blank was taking 30s and the cheap stuff was gone by then). The vendor list needs Blank because its blank search has to see the whole AH.

Never set the price source to None. Any item without a max price then counts as a hit at ANY price.

A few extras while you snipe:
- **Scroll wheel buys.** While the Buy panel is open, scrolling the mouse wheel presses Buy for you (it's still your input, and Point Blank Sniper still refuses anything over the max)
- **A red NOT BOUGHT banner.** When a buy fails you get the item and the reason over the bottom of the results for 8 seconds (Point Blank Sniper says "Sold" either way, so it was hard to tell). If the game never answers it says MAYBE NOT BOUGHT, so check your mail before buying it again
- **Straight back to scanning.** If it's already sold, bid only or the buy failed, the scan restarts 0.2 seconds later. A buy that MAY still be going through gets 1 to 2 seconds to finish first
- **Rogue poisons are skipped.** Item data says merchants pay for them but, the Forever server wont buy them, so the 25 poisons are blocked from the vendor scan

NOT BOUGHT reasons:

| What it says | What happened |
|---|---|
| Internal auction error | Most likely someone got there first |
| Cancelled before paying | The price went up, it sold, or the Buy panel closed |
| The purchase failed | Most likely someone got there first |
| Anything else | The game's own message (not enough gold etc.) |

## Selling

When you put a stack in Auctionator's Selling tab, FlipLists checks the price before you press Post:

1. **Undercut the cheapest listing** by your Auctionator undercut (I use Set Value 1c)
2. **Skip thin listings.** If the cheapest few listings hold fewer units than you're posting (20 at a Min), they will sell in minutes anyway, so it undercuts the first real one past them
3. **Skip dumps.** Anything under 80% of the market price is someone dumping stock, so it's skipped and you never post below that line
4. **Never jump past your own listing.** If you already have one up, it matches it
5. **Never sell at a loss.** It wont go below break-even on what you paid (after the 5% cut), or below what a merchant would pay

Whenever it changes the price, a `Price:` line in the Flips chat tab says why. For example:

```
Price: [Swiftthistle] at 3s 34c: skipped 3 under 80% of market 3s 83c
```

(3 were listed at 3s, the 80% line was 3s 07c, so it undercut the next real listing instead of selling at 2s 99c.)

You can always type over the price. Gear only gets rule 5 (every piece is its own listing).

## The Flips ledger

FlipLists keeps its own record of every buy and sale:

- AH buys are logged when you take the item from the mail (one row per attachment, a big buy can come as several)
- AH sales are logged when you take the gold from the mail, after the 5% cut
- Merchant sales are logged as you sell, and buyback undoes the sale
- If you used TSM before, its buy and sale log is copied in once on the first login

A sale only counts as a **flip** against something you bought earlier and hadnt sold yet (oldest first). Anything you sell beyond that is loot you gathered, so it shows up as **looted sales** instead of inflating your flip profit.

Where to see it:
- **Flips tab** in the auction house (next to Sniping)
- **`/flips`** opens the same thing anywhere
- **Minimap button** (the gold coin): click for Flips, right-click to export, drag it around the minimap to move it

At the top you get your flip profit, looted sales and what your held stock is worth. Each row is an item with bought, sold, held and profit, and anything you sold shows first so losses never hide at the bottom.

## Flips chat tab

A Flips chat tab is made for you on first login. Every snipe you buy is logged there with why you bought it and the best way to sell it:

```
24 Nov 14:12  Bought 20x [Iron Bar] at 2s 40c each, to RESELL on the AH (Flip Snipe). Best exit AH 3s 42c each
```

The last 60 lines come back (greyed out) after a reload. Item tooltips get a Best exit line too: the higher of our AH price after the cut and the merchant price.

## Exporting

Your ledger is yours (it's saved in your own WTF folder, nothing is uploaded anywhere). To get it out:

- `/flips export`, or right-click the minimap button, or
- Esc → Options → AddOns → Flip Lists → Export Flips (CSV)

A window opens with the whole ledger already selected. Press Ctrl+C and paste it into a spreadsheet. The columns are:

```
type,date,item id,item name,quantity,copper each
```

(Sales are after the 5% AH cut. An item the game hasnt loaded yet comes out with a blank name, opening the export again usually fills it in.)

The settings page also has a tickbox to hide the minimap button, and your realm type.

## Is the data fresh?

- The login line ends with `AH data from HH:MM`
- When you open the AH, a red warning shows if your prices are more than 3.5 hours old, so you know to update in WowUp and `/reload`

## Running it yourself

Only needed if you want your own copy of the hourly pull. Fork the repo, then:

1. Make a Blizzard API client at https://develop.battle.net/access/clients
2. Add two repository secrets: `BLIZZARD_CLIENT_ID` and `BLIZZARD_CLIENT_SECRET`
3. Run the AH pull and release workflow from the Actions tab

GitHub's own hourly schedule is unreliable (on my account it fires every 5 to 9 hours), so I use a free external cron (cron-job.org) to call the workflow every hour instead:

```
POST https://api.github.com/repos/<you>/wow-forever-flips/actions/workflows/pull.yml/dispatches
Authorization: Bearer <fine-grained token with Actions: read and write on this repo>
Accept: application/vnd.github+json

{"ref": "main"}
```

The first run starts with empty databases, so the max prices kick in after a day of data. To start with history, upload `ah.sqlite` (a Normal Alliance database, it gets renamed to `ah-111.sqlite`) and `item_ids.json` as a prerelease tagged `seed` and the first run picks them up.

On your own PC (Python 3.11+):

```bash
cp config.example.toml config.toml   # then fill in your client id and secret
python3 ah_pull.py                   # pull the latest snapshot of all 8 houses into data/
FLIPLISTS_ADDON="/path/to/_forever_/Interface/AddOns/FlipLists" python3 sync_lists.py
python3 ah_pull.py report            # best items NOT on the snipe list, by gold sold per day
python3 ah_pull.py report 10000 114  # the same for another house (cap in copper, then house number)
```

The shopping lists live in `lists.txt`, one list per line, items separated by `^`.

## Good to know

- It wont buy or post anything by itself, every click is yours
- New prices need a `/reload`, there's no way round that for addons
- EU Forever only, and Blackwater isnt covered
- If you have characters on different realm types, tick the right one on each (it's saved per character)
- If it breaks something, `/console scriptErrors 1` shows the Lua error (WoW hides them by default) and an issue with that error would be brill

Any ideas or anything look off? Open an issue :)
