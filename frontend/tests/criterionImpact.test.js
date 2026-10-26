import assert from "node:assert/strict";
import test from "node:test";

import { criterionImpactLabel } from "../src/utils/criterionImpact.js";

test("inclusion impact labels reflect whether the requirement is met", () => {
  assert.equal(criterionImpactLabel("SUPPORTS", "INCLUSION"), "Met");
  assert.equal(criterionImpactLabel("BLOCKS", "INCLUSION"), "Not met");
});

test("exclusion impact labels reflect whether the exclusion is met", () => {
  assert.equal(criterionImpactLabel("BLOCKS", "EXCLUSION"), "Met");
  assert.equal(criterionImpactLabel("SUPPORTS", "EXCLUSION"), "Not met");
});

test("unknown evidence remains unassessed for either criterion type", () => {
  assert.equal(criterionImpactLabel("UNKNOWN", "INCLUSION"), "Could not assess");
  assert.equal(criterionImpactLabel("UNKNOWN", "EXCLUSION"), "Could not assess");
});
