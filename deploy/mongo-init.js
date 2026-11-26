// Runs once, the first time MongoDB starts with an empty data volume.
// Creates the account the API uses: it can read and write the babybabel database and nothing else.
const appDb = db.getSiblingDB("babybabel");
appDb.createUser({
  user: "babybabel",
  pwd: process.env.MONGO_APP_PASSWORD,
  roles: [{ role: "readWrite", db: "babybabel" }],
});
