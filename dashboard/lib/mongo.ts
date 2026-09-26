import { MongoClient, type Db } from "mongodb";

const globalForMongo = globalThis as unknown as { _hfClient?: Promise<MongoClient> };

export function hfDb(): Promise<Db> {
  const uri = process.env.MONGODB_URI;
  if (!uri) throw new Error("MONGODB_URI is not configured");
  if (!globalForMongo._hfClient) {
    globalForMongo._hfClient = new MongoClient(uri, {
      appName: "harnessforge-dashboard",
      maxPoolSize: 5,
      serverSelectionTimeoutMS: 8000,
    })
      .connect()
      .catch((err) => {
        globalForMongo._hfClient = undefined; // never cache a failed connection; retry on the next request
        throw err;
      });
  }
  return globalForMongo._hfClient.then((c) => c.db(process.env.HF_DB || "harnessforge"));
}
