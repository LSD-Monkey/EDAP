# Trade Tab

Finds the best **round trips** from a start station (similar to the trade routes on Inara) and starts one directly
with Waypoint Assist.

1. Dock at the station you want to start from and click **Current station** (fills in system, station, cargo
   capacity, pad size and the laden jump range from your last jumps).
2. Set the filters and click **Search**:
   * *Max. distance (ly)* – direct distance between the two stations.
   * *Max. arrival (Ls)* – distance of the station from the arrival star (long supercruise = less profit/hour).
   * *Max. data age (h)* – ignore older prices.
   * *Pad* – min. landing pad (L for a Type-9). *Planetary* – include stations on planets.
3. The list shows per destination: distance, estimated jumps, what to buy here and sell there (profit per ton),
   what to bring back, profit per round trip and the estimated profit per hour. Click a column header to sort.
4. **Start trade route** (or double click) writes `waypoints/trade_<start>_<destination>.json`
   (start station, destination, REPEAT), loads it and starts Waypoint Assist. It runs until you stop it.
   **Save as waypoint file** only writes and loads the file.

How it works:

* The market of the start station comes from your `Market.json` when you are docked there (exact prices), other
  markets from the [Ardent Insight API](https://github.com/iaincollins/ardent-api) (EDDN data uploaded by players).
* For every commodity the start station sells, the best buyers within the distance are searched. The best
  destinations get their market loaded to find the most profitable commodity for the way back.
* Excluded: fleet carriers, megaships, construction sites, stations without the required pad size (or unknown pad
  size), planetary stations (unless enabled).
* Time estimate per round trip: ~110 s per jump (`TradeSecsPerJump` in AP.json, measured with EDAP incl.
  alignment and star avoidance), supercruise by distance to the star, ~4 min per station for docking and trading.
* Prices change: the market data can be hours old and other players trade the same route. Check the profit after
  the first round trip.
