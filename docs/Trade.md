# Trade Tab

Searches the most profitable trade routes around your ship, similar to the trade route search of Inara, and starts
one directly with Waypoint Assist.

## Search

| Field | Meaning |
|---|---|
| Reference system | Centre of the search. *Current location* fills in your system and your ship (cargo, pad size, laden jump range from your last jumps). |
| Route type | *Round trips*: A -> B with one commodity, B -> A with another, repeated. *One way*: buy at A, sell at B. |
| Max. to start (ly) | Max. distance from the reference system to the first station of the route. |
| Station to station (ly) | Max. direct distance between the two stations. |
| Max. from star (Ls) | Max. distance of a station from the arrival star (long supercruise costs time). |
| Cargo (t) | Cargo capacity, used for the amount per trip. |
| Min. supply/demand | Min. stock at the seller and demand at the buyer. 0 = your cargo capacity. |
| Max. price age (h) | Ignore market data older than this. |
| Landing pad | Min. landing pad size. |
| Jump range (ly) | Laden jump range, for the estimate of the jumps and the time. |
| Commodities | Number of commodities searched, the most valuable first. More = slower, more results. |
| Fleet carriers / Megaships / Planetary ports / Odyssey settlements | Include these stations. Off by default. |
| Sort by | Profit per hour, profit per trip, distance between the stations, distance to start. Click a column header to sort by that column. |

The search area is the max. distance to start plus the max. distance between the stations (max. 500 ly). A round
trip starts at the station that is closer to you.

## Results

From (start), To, distance to the start station, distance between the stations, the longer star distance of the
two stations, the commodity on the way there and on the way back with the profit per ton, profit per trip,
estimated profit per hour and the age of the prices. The line below shows all details (prices, supply, demand,
station types, jumps, time per trip, capital needed).

**Start trade route** (or double click) writes `waypoints/trade_<start>_<destination>.json`, loads it and starts
Waypoint Assist: fly to the start station, buy, fly, sell (round trip: buy, fly back, sell, repeat) until you stop
it. **Save as waypoint file** only writes and loads the file.

## How it works

* Market data comes from the [Ardent Insight API](https://github.com/iaincollins/ardent-api) (EDDN data uploaded by
  players, the same source Inara and others use).
* For every commodity (the most valuable first) the sellers and the buyers around the reference system are loaded.
  Every seller/buyer pair within the max. distance between the stations is a trade; trades A->B and B->A make a
  round trip.
* Always excluded: construction sites and colonisation ships. Stations with unknown pad size are excluded when
  pad M or L is required.
* Time estimate: ~110 s per jump (`TradeSecsPerJump` in AP.json, measured with EDAP incl. alignment and star
  avoidance), supercruise by distance to the star, ~4 min per station for docking and trading.
* Prices change and other players trade the same routes. Check the profit after the first trip.
