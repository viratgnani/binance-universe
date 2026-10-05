# Binance USDⓈ-M Futures Order Book API Contract

## 1. REST Depth Snapshot

Endpoint: `GET /fapi/v1/depth`
Limits: Supports limits of 5, 10, 20, 50, 100, 500, 1000. Weight varies (2, 5, 10, 20).

Response structure:
```json
{
  "lastUpdateId": 11446210594643,
  "E": 1788271369915,   // Message output time
  "T": 1788271369912,   // Transaction time
  "bids": [
    [
      "78142.70",       // Price level
      "7.128"           // Quantity
    ]
  ],
  "asks": [
    [
      "78142.80",
      "1.077"
    ]
  ]
}
```

## 2. WebSocket Diff.Depth Stream

Endpoint: `wss://fstream.binance.com/ws/<symbol>@depth` or `@depth@100ms` / `@depth@500ms`

Event structure:
```json
{
  "e": "depthUpdate", // Event type
  "E": 123456789,     // Event time
  "T": 123456788,     // Transaction time
  "s": "BTCUSDT",     // Symbol
  "U": 157,           // First update ID in event
  "u": 160,           // Final update ID in event
  "pu": 149,          // Final update Id in last stream (ie `u` in last event)
  "b": [              // Bids to be updated
    [
      "0.0024",       // Price level to be updated
      "10"            // Quantity
    ]
  ],
  "a": [              // Asks to be updated
    [
      "0.0026",       // Price level to be updated
      "100"           // Quantity
    ]
  ]
}
```

## 3. Synchronization Rules (USDⓈ-M Futures specific)

1. Connect to the WebSocket stream and immediately begin buffering all received `depthUpdate` events.
2. Fetch a depth snapshot via the REST API (`/fapi/v1/depth?symbol=BTCUSDT&limit=1000`).
3. Discard any buffered WebSocket events where the event's final update ID (`u`) is <= the snapshot's `lastUpdateId`.
4. The **first** processed WebSocket event must satisfy:
   - `U` (first update ID) <= `lastUpdateId`
   - `u` (final update ID) >= `lastUpdateId`
5. For all subsequent events, the event's previous update ID (`pu`) must exactly equal the previous event's final update ID (`u`).
6. If rule #5 is violated, or if the first valid event is not found matching rule #4, the local book is considered unsynchronized and the entire synchronization process (steps 1-5) must be restarted.
7. To maintain the local order book, apply each valid event:
   - If a price level's quantity is `"0"`, the price level should be removed from the local order book.
   - If the quantity is `> 0`, the price level should be inserted or updated in the local order book.
