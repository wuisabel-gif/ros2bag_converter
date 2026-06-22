# ros2bag-convert (Node.js)

Inspect ROS 2 `.db3` bags and export topics to CSV / JSON from the terminal.
Same decoder as the [web app](https://wuisabel-gif.github.io/ros2bag_converter/).
Reads SQLite via [`sql.js`](https://sql.js.org/) (pure WebAssembly — no native build step).

## Install

```bash
# from a clone of the repo
npm install -g ./cli/node
# or run without installing
npx ./cli/node info my_bag.db3
```

## Use

```bash
ros2bag-convert <bag.db3> [options]   # export (default command)
ros2bag-convert info <bag.db3>        # summary
ros2bag-convert list <bag.db3>        # topics + counts
```

| Option | Meaning |
|---|---|
| `-f, --format <csv\|json>` | output format (default `csv`) |
| `-o, --output <file>` | write to file (default stdout) |
| `-t, --topic <name>` | include topic; repeatable (default all) |
| `-m, --metadata <file>` | `metadata.yaml` for storage/distro info |
| `--max-rows <n>` | per-topic row cap (default 500000) |

```bash
ros2bag-convert my_bag.db3 -f csv -t /odom -o odom.csv
ros2bag-convert my_bag.db3 -f json > all.json
```

## Library API

```js
const { openBag, eachMessage } = require('ros2bag-convert/bag');
const { decodeMessage, flatten } = require('ros2bag-convert');

const { db, topics } = await openBag('my_bag.db3');
const t = topics.find(x => x.name === '/odom');
eachMessage(db, t.id, (ts, data) => {
  console.log(Number(ts) / 1e9, decodeMessage(t.type, data));
});
db.close();
```

## Test

```bash
npm test   # encodes CDR blobs, builds a synthetic .db3, checks decode end-to-end
```

Requires Node ≥ 16.
