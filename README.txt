================================================================================
                                  LiteChain
        Indian index, stock and commodity options through your Dhan account
================================================================================

WHAT IS LITECHAIN?
------------------
LiteChain is a browser dashboard for the option chains of NSE indices (NIFTY,
BANKNIFTY, FINNIFTY, NIFTYNXT50, MIDCPNIFTY), 224 NSE stocks and three MCX
commodity futures (crude oil, natural gas, gold), using data from Dhan's API
(https://dhanhq.co) with your own Dhan account. For one expiry at a time it
shows:
- the option chain as a table: for every strike, open interest, volume and the
  change in open interest (in lots), implied volatility, last traded price, a
  theoretical price (Black-Scholes; Black-76 for MCX), volatility exposure
  (VEX), gamma exposure (GEX), the put/call ratio and straddle open interest,
  with the max-pain strike outlined;
- or a page of charts built from the same figures, including Dhan's own Greeks
  (delta, gamma, vega, theta) by strike.

It runs in Docker and is reachable only from your own computer. It stores
nothing on disk: every figure is fetched from Dhan when you ask for it.

Calls are shown in red and puts in green, in the table and in every chart.


BEFORE YOU START -- READ THIS
-----------------------------
1. You need a Dhan account with Dhan's Data API.
   Option-chain data comes from Dhan's paid Data API subscription (Rs 499 plus
   taxes a month according to Dhan's support pages in November 2026; check
   Dhan's current terms). You also need your Dhan client ID and an access
   token, created on Dhan's website: web.dhan.co -> My Profile -> Access
   DhanHQ APIs -> Generate Access Token. Dhan's support pages (November 2026)
   say a token is valid for 24 hours, so expect to create a new one each day.

2. LOT SIZES ARE NOT UPDATED AUTOMATICALLY -- CHECK AND UPDATE THEM YOURSELF.
   Every figure the table shows "in lots" is Dhan's figure divided by the lot
   size written in assets.csv. That file is fixed: it does not follow the
   exchanges, which revise lot sizes from time to time. For example, the NSE
   cut its index lot sizes after 30 December 2025 (NIFTY 75 -> 65, BANKNIFTY
   35 -> 30, FINNIFTY 65 -> 60, MIDCPNIFTY 140 -> 120), and assets.csv still
   holds the earlier sizes; stock and commodity lot sizes change too.
   Before relying on any lot figure, check the current lot size on the NSE's
   or MCX's website (or with your broker) and correct the lot_size column of
   assets.csv. Stop the app first and start it again afterwards.

3. MCX ASSETS ARE FUTURES CONTRACTS -- THEIR IDs CHANGE AND MUST BE UPDATED BY
   HAND.
   The three MCX rows in assets.csv (CrudeOil, NatGas, Gold) are each one
   futures contract, named in the asset_id column by Dhan's ID for that
   contract. When that contract expires, the next one takes over with a new
   ID, and the old ID no longer gives an option chain. Regularly, and before
   using an MCX asset after an expiry, find the ID of the current futures
   contract in the instrument list Dhan publishes -- a CSV file of every
   instrument with its Security ID, linked from Dhan's API documentation page
   "Instrument List" (https://dhanhq.co/docs/v2/instruments) -- and type it by
   hand into the asset_id column of assets.csv, checking the lot_size column
   at the same time. Stop the app first and start it again afterwards.


SYSTEM REQUIREMENTS
-------------------
- Docker Desktop: https://www.docker.com/products/docker-desktop
  (Windows 10/11, macOS, or Linux with Docker). Python does not need to be
  installed on your computer.
- An internet connection.
- A Dhan account with Data API access (see above).


YOUR DHAN CREDENTIALS
---------------------
Two ways to give LiteChain your client ID and access token:

A. In the app. When it starts without credentials, LiteChain shows a setup
   screen; type them in and choose "Save to Session". They are kept in the
   app's memory for that browser tab only, are not written to disk, and are
   gone when the session ends. Settings -> "Update API Keys" lets you change
   them; the token is shown masked there.

B. In a file. Copy .streamlit/secrets.toml.example to .streamlit/secrets.toml
   and put your client ID and access token in place of the placeholders. The
   file is kept out of git (never commit it). It is copied into the app when
   Docker builds it, so after changing it, stop and start the app again.

If Dhan rejects the token (for example once it has expired), create a new one
in Dhan and enter it again.


STARTING AND STOPPING
---------------------
1. Install Docker Desktop, start it, and wait until it is running.
2. Start:  double-click lite.command (macOS) or lite.bat (Windows).
   If macOS will not open it, right-click it and choose Open.
   On Linux, run  docker compose up -d --build  in this folder (or
   docker-compose up -d --build  on older installs) and open
   http://localhost:8501 yourself.
   The script builds the app (only what changed is rebuilt), starts it,
   waits 6 seconds and opens http://localhost:8501. The first start downloads
   and installs everything and can take a few minutes -- refresh the page
   once it has finished.
3. Stop:   double-click STOP-lite.command or STOP-lite.bat.

The dashboard is published on this computer only (127.0.0.1:8501), not to
other devices on your network.


USING THE DASHBOARD
-------------------
The "Markets" panel in the sidebar, top to bottom:

Segment         Index, Equity or Commodity.
Asset           The assets of that segment, from assets.csv.
Expiry          The expiry dates Dhan lists for that asset.
View            Chain (the table) or Charts.
Strike Range    How many strikes to show either side of the strike nearest the
                current price: +-8, +-10, +-12, +-16 (the default), +-32, or
                All Strikes. Every figure the app works out -- max pain,
                support and resistance, the totals row and the figures above
                the charts -- covers only the strikes shown. Choose All
                Strikes for whole-chain figures (max pain, in particular, is
                meant to cover the whole chain).
Auto Refresh    Chain view only: 3s, 5s, 30s, 5m or 15m. While it is set, the
                table is fetched again at that interval ("3s" waits 3.5
                seconds).
Volatility      The volatility (%) used for the BS Price column; default 10.
Risk-Free Rate  The interest rate (%) used for the BS Price column;
                default 7.
Fetch Data      Fetches the option chain and works out every figure.

The "Settings" panel holds the credential buttons, a Debug Mode switch (shows
load times and error details) and the app's version.


THE TABLE (CHAIN VIEW)
----------------------
From left to right: GEX (OI) and PCR (OI/Vol); the call columns VEX, BS Price,
IV, OI Chg, OI, Volume, LTP; STRIKE; the same seven columns for puts in mirror
order; and Strd OI.

How every figure is arrived at:

OI, Volume, OI Chg -- in lots
   Dhan's open interest and volume for the contract, divided by the lot size
   in assets.csv (see BEFORE YOU START). For MCX commodities the app treats
   Dhan's figures as already being in lots. OI Chg is Dhan's open interest
   minus Dhan's "previous OI" figure for the contract, in lots.
   Under each figure, in brackets: its share of the largest figure on the
   same side (calls or puts).

IV
   Dhan's implied volatility for the contract, an annual percentage (Dhan's
   documentation example shows values such as 9.79).

LTP
   The contract's last traded price, in rupees.

BS Price
   A theoretical price worked out by the app from the current price, the
   strike, the time to expiry, and the volatility and rate you set in the
   sidebar -- one volatility for every strike. It is a comparison price, not a
   market price. NSE options use the Black-Scholes formula; MCX options use
   Black-76, the form of Black-Scholes for options on futures, because every
   MCX asset here is a futures contract.
   Time to expiry: the time from now, in India time, to the market's close on
   the expiry date, divided by 365 days. The close is 15:30 for NSE; for MCX
   it is 23:30 while the US is on daylight saving time (second Sunday of March
   to first Sunday of November) and 23:55 otherwise -- MCX's schedule as of
   November 2026. If MCX changes its hours, change market_close in
   integrated.py.

VEX (volatility exposure)
   Dhan's vega for the contract x its open interest / the lot size, shown in
   thousands (K), with its share of the largest on the same side. A contract
   with no VEX (no open interest) shows "-" alone, with no share.

GEX (OI) (gamma exposure)
   For each contract: 0.01 x the current price x open interest x gamma, with
   calls counted negative and puts positive; added up for the strike and shown
   in millions (M) with three decimals. The sign convention assumes option
   dealers are short the calls and long the puts.
   The unit is units of the underlying (shares, index units or commodity
   units), not rupees: the amount by which option dealers' hedges would change
   for a 1% move in the price. Example: NIFTY at 26,000, open interest of
   9,750,000 units at a strike, gamma 0.0004 -> 0.01 x 26,000 x 9,750,000 x
   0.0004 = 1,014,000 units, shown as 1.014M. In rupees that would be about
   26,000 times larger.
   Small values: a strike under 500 units shows 0.000M (never -0.000M); a
   strike with no GEX at all shows "-".
   The bracketed share compares each strike with the largest strike in either
   direction, so it runs from -100% to 100%: 100% is the largest positive
   strike if that is the biggest in size, -100% the most negative if that is.

PCR (OI/Vol)
   Put open interest / call open interest at that strike, and below it put
   volume / call volume. "-" stands where the call figure is zero (no ratio
   exists); the same holds for the ratios in the TOTALS row.

Strd OI
   Straddle open interest: call plus put open interest at that strike, in
   lots.

The highlighted row is the current price: between the two strikes around it,
or directly above a strike it equals exactly. The strike with the max pain --
the expiry price at which option writers would pay out least, from the open
interest at every strike -- has a purple outline.

The TOTALS row gives total GEX; the put/call ratios of the totals; total open
interest, OI change and volume for calls and for puts; "OI Diff" (put minus
call open interest, in lots) in the strike column; and total straddle open
interest.

Highlights, on each side separately:
- OI, Volume and VEX: the largest figure has a green background, the second
  an amber background, the third a blue border.
- OI Chg: the two largest increases have green borders, the two largest
  decreases red borders.
- GEX: the largest positive strike has a green border, the most negative a
  red border. Strd OI: the three largest are highlighted like OI.


THE CHARTS (CHARTS VIEW)
------------------------
Above the charts:
- Total, Call and Put GEX, in millions (M) with three decimals -- the same
  figures, in the same format, as the table, the GEX chart's title and its
  hover.
- Total, Call and Put VEX, in thousands (K); VEX Ratio (call VEX / put VEX);
  VEX Skew ((call VEX - put VEX) / total VEX).
- Implied volatility: average, at the money (the strike nearest the price),
  calls' and puts' averages, skew (put average minus call average) and range.

The charts:
- Gamma Exposure by Strike, in millions (green above zero, red below).
- IV Smile Curve: implied volatility (%) by strike, calls and puts.
- Open Interest, OI Change and Volume by strike, in lots (open interest and
  volume on a square-root scale, so small bars stay visible).
- Support & Resistance: the three call strikes with the most open interest
  (resistance) and the three put strikes with the most (support), in lots;
  the two largest of each are marked "Strong".
- Delta, Gamma, Vega and Theta by strike: Dhan's own Greeks, as Dhan sends
  them. The app does not calculate Greeks.

The dashed orange line is the current price. Strikes are on a numeric axis:
on the bar charts each call bar sits just left of its strike and each put bar
just right of it; as many strike labels are shown as fit the chart's width.
Hovering shows each bar's or point's figures and, on the strike charts,
whether the option is in the money (ITM), at the money (ATM, within 2% of the
price) or out of the money (OTM) -- a call is in the money below the price, a
put above it. Chart text follows Streamlit's light or dark page.


DATA LIMITATIONS -- READ THIS
-----------------------------
- Every figure comes from Dhan at the moment you fetch it; the app does not
  store or check them.
- Lot figures are only as right as the lot sizes in assets.csv (see BEFORE
  YOU START).
- Every calculated figure, max pain included, covers only the strikes in the
  chosen Strike Range; All Strikes gives whole-chain figures.
- The BS Price (Black-Scholes for NSE, Black-76 for MCX) uses one volatility
  for every strike, European-style exercise and no dividends: a reference,
  not a fair value.
- GEX and VEX are simple estimates from Dhan's Greeks and open interest, under
  the assumptions stated above.
- Many strikes far from the price trade little or not at all.
- Dhan's own terms govern the use of its data. LiteChain is not affiliated
  with Dhan.


TROUBLESHOOTING
---------------
"Docker Desktop is not running"
   Start Docker Desktop, wait until it is running, then start the app again.

"Port 8501 already in use"
   Another program is using port 8501 (another dashboard, for example).
   Stop it, or run STOP-lite first.

The page does not load
   Wait a minute -- the first start installs everything -- then refresh.
   Check in Docker Desktop that the litechain container is running.

"Failed to fetch data", "No expiry dates available", "Connection Failed"
   Check your internet connection, your Data API subscription and your
   credentials; create a new access token if the old one has expired.
   Each request is retried three times before the message appears.
   For an MCX asset, "No expiry dates available" usually means its futures
   contract has expired and the ID in assets.csv is out of date: put in the
   current contract's ID (see BEFORE YOU START, item 3).


TECHNICAL DETAILS
-----------------
- Python 3.11 (in the container), Streamlit, Altair, pandas, NumPy, SciPy,
  requests.
- Container name: litechain. Port: 8501, on this computer only.
- Requests to Dhan are spaced apart (3 seconds to start with, adjusting to
  Dhan's replies) and retried three times.
- Files:
     app.py              the page, the sidebar and the table
     integrated.py       Dhan requests and every calculation
     visualization.py    the charts
     credentials.py      the credentials screen
     assets.csv          the assets and their lot sizes
     styles.css          the table's colours and layout
     .streamlit/secrets.toml.example   template for your credentials file
     Dockerfile, docker-compose.yml, .dockerignore
     lite.* / STOP-lite.*   double-click start and stop scripts


LICENCE
-------
MIT - see LICENSE. Streamlit, Altair, pandas, NumPy, SciPy and requests are
installed by pip from requirements.txt and keep their own licences. The market
data is Dhan's; Dhan's own terms govern its use.


================================================================================
                    From ChorBazaar - https://chorbazaar.co.in
================================================================================
