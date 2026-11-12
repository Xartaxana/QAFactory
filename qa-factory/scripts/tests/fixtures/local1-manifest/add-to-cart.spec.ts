import { test, expect } from '../../../core/fixtures/cart.fixture';
import { expectStableErrorShape, expectRefused } from '../../../core/contracts/validators/errorShape';

// T-1: the same setup and action (add, then read the cart back) for three actors; one title per
// partition of LOCAL-1_TC_001 so each instance id names its partition.
type Shop = Parameters<Parameters<typeof test>[2]>[0]['shop'];

async function addAndReadBack(shop: Shop, entry: 'guest' | 'user' | 'merge', added: number) {
  const book = await shop.book(5);
  let reader;
  if (entry === 'guest') {
    reader = await shop.guest();
  } else if (entry === 'user') {
    reader = await shop.user();
  } else {
    const account = await shop.account();
    reader = await shop.guest();
    expect((await reader.addToCart(book.id, added)).status, 'guest add accepted').toBeLessThan(300);
    await reader.signIn(account.email, account.password);
    expect((await reader.mergeGuestCart()).status, 'merge answered').toBe(200);
    return { lines: (await reader.readCart()).filter((l) => l.bookId === book.id) };
  }
  expect((await reader.addToCart(book.id, added)).status, 'add accepted').toBeLessThan(300);
  return { lines: (await reader.readCart()).filter((l) => l.bookId === book.id) };
}

test('@regression LOCAL-1_TC_001 P-guest-qty1 guest add of one book appears in the cart read', async ({ shop }) => {
  const { lines } = await addAndReadBack(shop, 'guest', 1);
  expect(lines.length, 'Then 1: exactly one line for the own book').toBe(1);
  expect(lines[0].quantity, 'Then 1: quantity 1').toBe(1);
});

test('@regression LOCAL-1_TC_001 P-user-qty3 signed-in add of three appears in the cart read', async ({ shop }) => {
  const { lines } = await addAndReadBack(shop, 'user', 3);
  expect(lines.length, 'Then 2: exactly one line for the own book').toBe(1);
  expect(lines[0].quantity, 'Then 2: quantity 3').toBe(3);
});

test('@regression LOCAL-1_TC_001 P-merge guest cart is in the account cart after the sign-in merge', async ({ shop }) => {
  const { lines } = await addAndReadBack(shop, 'merge', 2);
  expect(lines.length, 'Then 3: a line for the own book after the merge').toBe(1);
  expect(lines[0].quantity, 'Then 3: quantity at least 1').toBeGreaterThanOrEqual(1);
});

test('@regression LOCAL-1_TC_007 add of an unknown book id is refused with a stable error shape, cart unchanged', async ({ shop }) => {
  const book = await shop.book(5);
  const actor = await shop.guest();
  const u1 = await shop.unknownBookId(book.id);
  const u2 = await shop.unknownBookId(u1);

  const before = await actor.readCart();
  const r1 = await actor.addToCart(u1, 1);
  const r2 = await actor.addToCart(u2, 1);
  const after = await actor.readCart();

  // Independent Thens first, so a red shape check does not hide them
  expect(after, 'Then 2: cart after the refusals equals the cart before').toEqual(before);
  const control = await actor.addToCart(book.id, 1);
  expect(control.status, 'Then 3: control add accepted').toBeLessThan(300);
  expect((await actor.readCart()).some((l) => l.bookId === book.id), 'Then 3: own book is in the cart').toBe(true);
  expectStableErrorShape([r1, r2], 'Then 1');
});

test('@regression LOCAL-1_TC_008 add of an out-of-stock book is refused, stock-1 boundary accepted', async ({ shop }) => {
  const zero = await shop.book(0);
  const one = await shop.book(1);
  const actor = await shop.guest();

  const before = await actor.readCart();
  const r1 = await actor.addToCart(zero.id, 1);
  const r2 = await actor.addToCart(zero.id, 1);
  const after = await actor.readCart();
  expect(after, 'Then 2: cart after the refusals equals the cart before').toEqual(before);

  const control = await actor.addToCart(one.id, 1);
  expect(control.status, 'Then 3: stock-1 add accepted').toBeLessThan(300);
  const lines = (await actor.readCart()).filter((l) => l.bookId === one.id);
  expect(lines.length, 'Then 3: one line for the stock-1 book').toBe(1);
  expect(lines[0].quantity, 'Then 3: quantity 1').toBe(1);

  expectStableErrorShape([r1, r2], 'Then 1');
});

test('@regression LOCAL-1_TC_009 add beyond stock is refused for an empty cart and an existing line', async ({ shop }) => {
  const a = await shop.book(3);
  const c = await shop.book(3);
  const fill = await shop.guest();
  const over = await shop.guest();
  const line = await shop.guest();
  const qtyOf = async (who: typeof fill, bookId: number) => (await who.readCart()).filter((l) => l.bookId === bookId).map((l) => l.quantity);

  // P-empty-cart
  expect((await fill.addToCart(a.id, 3)).status, 'Then 1: quantity = stock accepted').toBeLessThan(300);
  expect(await qtyOf(fill, a.id), 'Then 1: cart shows 3').toEqual([3]);
  expectRefused(await over.addToCart(a.id, 4), 'Then 2: quantity stock+1 refused');
  expect(await over.readCart(), 'Then 2: cart stays empty').toEqual([]);

  // P-existing-line
  expect((await line.addToCart(c.id, 2)).status, 'setup: line of 2').toBeLessThan(300);
  expectRefused(await line.addToCart(c.id, 2), 'Then 3: total over stock refused');
  expect(await qtyOf(line, c.id), 'Then 3: line still reads 2').toEqual([2]);
  expect((await line.addToCart(c.id, 1)).status, 'Then 4: total exactly stock accepted').toBeLessThan(300);
  expect(await qtyOf(line, c.id), 'Then 4: line reads 3').toEqual([3]);
});

test('@regression LOCAL-1_TC_010 repeat add of the same book sums quantities in one line', async ({ shop }) => {
  const b = await shop.book(5);
  const actor = await shop.guest();
  expect((await actor.addToCart(b.id, 1)).status, 'setup: first add accepted').toBeLessThan(300);
  expect((await actor.addToCart(b.id, 2)).status, 'setup: second add accepted').toBeLessThan(300);

  const lines = (await actor.readCart()).filter((l) => l.bookId === b.id);
  expect.soft(lines.length, 'Then 1: exactly one line for B').toBe(1);
  expect.soft(lines.map((l) => l.quantity), 'Then 2: the line reads the sum 1 + 2').toEqual([3]);
});

test('@regression LOCAL-1_TC_011 invalid quantity and book id payloads are rejected, edges 1 and 999 accepted', async ({ shop }) => {
  const b = await shop.book(1500);
  const badQty = await shop.guest();
  const badId = await shop.guest();
  const edge1 = await shop.guest();
  const edge999 = await shop.guest();

  // P-bad-quantity
  const q = [];
  for (const quantity of [0, 1000, 1.5]) q.push(await badQty.addRaw({ bookId: b.id, quantity }));
  // P-bad-bookid
  const ids = [];
  for (const bookId of [0, -1, 1.5, 'abc']) ids.push(await badId.addRaw({ bookId, quantity: 1 }));
  // P-edges
  const e1 = await edge1.addToCart(b.id, 1);
  const e999 = await edge999.addToCart(b.id, 999);

  // Cart reads and edges first, the shape checks (soft) after them
  expect.soft(await badQty.readCart(), 'Then 1: cart empty after the quantity refusals').toEqual([]);
  expect.soft(await badId.readCart(), 'Then 2: cart empty after the book id refusals').toEqual([]);
  expect.soft(e1.status, 'Then 3: quantity 1 accepted').toBeLessThan(300);
  expect.soft((await edge1.readCart()).map((l) => l.quantity), 'Then 3: cart reads 1').toEqual([1]);
  expect.soft(e999.status, 'Then 3: quantity 999 accepted').toBeLessThan(300);
  expect.soft((await edge999.readCart()).map((l) => l.quantity), 'Then 3: cart reads 999').toEqual([999]);
  expectStableErrorShape(q, 'Then 1', true);
  expectStableErrorShape(ids, 'Then 2', true);
});

test('@regression LOCAL-1_TC_012 guest and user carts are isolated', async ({ shop }) => {
  const b = await shop.book(5);
  const g1 = await shop.guest();
  const g2 = await shop.guest();
  const u = await shop.user();
  const g3 = await shop.guest();
  test.info().annotations.push({
    type: 'sessions',
    description: `G1 ${await g1.identity()} | G2 ${await g2.identity()} | U ${await u.identity()} | G3 ${await g3.identity()}`,
  });

  // P-guest-vs-guest
  expect((await g1.addToCart(b.id, 1)).status, 'setup: G1 add accepted').toBeLessThan(300);
  expect.soft((await g2.readCart()).filter((l) => l.bookId === b.id), 'Then 1: G2 cart does not contain B').toEqual([]);

  // P-user-vs-guest
  expect((await u.addToCart(b.id, 2)).status, 'setup: U add accepted').toBeLessThan(300);
  const uLines = await u.readCart();
  expect(uLines.map((l) => [l.bookId, l.quantity]), 'setup: U cart is B x 2').toEqual([[b.id, 2]]);
  const uLine = uLines[0];

  const g3Seen = await g3.readCart();
  expect.soft(g3Seen.filter((l) => l.id === uLine.id || l.bookId === b.id), 'Then 2: G3 cart does not contain U line').toEqual([]);

  const change = await g3.changeLine(uLine.id, 4);
  test.info().annotations.push({ type: 'g3-change-status', description: String(change.status) });
  expect.soft((await u.readCart()).map((l) => [l.bookId, l.quantity]), 'Then 3: U line for B still reads 2 after the change attempt').toEqual([[b.id, 2]]);

  const g3Add = await g3.addToCart(b.id, 1);
  expect.soft(g3Add.status, 'Then 4: G3 own add accepted').toBeLessThan(300);
  expect.soft((await u.readCart()).map((l) => [l.bookId, l.quantity]), 'Then 4: U cart is still only B x 2').toEqual([[b.id, 2]]);
});

test('@regression LOCAL-1_TC_013 guest cart merge on login follows the confirmed quantity, stock and zero-stock rules', async ({ shop }) => {
  const b1 = await shop.book(5);
  const b2 = await shop.book(3);
  const b3 = await shop.book(1);
  const b4 = await shop.book(5);
  const account = await shop.account();
  const accountJar = await shop.guest();
  await accountJar.signIn(account.email, account.password);
  const guest = await shop.guest();

  // account cart holds B1 x 3 and B2 x 2; guest cart holds B1 x 2, B2 x 3, B3 x 1, B4 x 2
  expect((await accountJar.addToCart(b1.id, 3)).status, 'setup: account B1').toBeLessThan(300);
  expect((await accountJar.addToCart(b2.id, 2)).status, 'setup: account B2').toBeLessThan(300);
  expect((await guest.addToCart(b1.id, 2)).status, 'setup: guest B1').toBeLessThan(300);
  expect((await guest.addToCart(b2.id, 3)).status, 'setup: guest B2').toBeLessThan(300);
  expect((await guest.addToCart(b3.id, 1)).status, 'setup: guest B3').toBeLessThan(300);
  expect((await guest.addToCart(b4.id, 2)).status, 'setup: guest B4').toBeLessThan(300);
  await shop.setStock(b3, 0);

  await guest.signIn(account.email, account.password);
  test.info().annotations.push({ type: 'sessions', description: `account jar ${await accountJar.identity()} | merging jar ${await guest.identity()}` });
  expect((await guest.mergeGuestCart()).status, 'merge answered').toBe(200);

  const cart = await accountJar.readCart();
  const qty = (id: number) => cart.filter((l) => l.bookId === id).map((l) => l.quantity);
  expect.soft(qty(b1.id), 'Then 1: B1 reads 3 (higher quantity wins)').toEqual([3]);
  expect.soft(qty(b2.id).reduce((a, n) => a + n, 0), 'Then 2: B2 reads no more than its stock 3').toBeLessThanOrEqual(3);
  expect.soft(qty(b3.id), 'Then 3: B3 (zero stock) is not in the merged cart').toEqual([]);
  expect.soft(qty(b4.id), 'Then 4: B4 is in the account cart with quantity 2').toEqual([2]);
});

test('@regression LOCAL-1_TC_016 update quantity respects stock, including zero stock', async ({ shop }) => {
  const a = await shop.book(3);
  const z = await shop.book(3);
  const jar = await shop.guest();
  expect((await jar.addToCart(a.id, 1)).status, 'setup: A add accepted').toBeLessThan(300);
  expect((await jar.addToCart(z.id, 1)).status, 'setup: Z add accepted').toBeLessThan(300);
  const lineOf = async (bookId: number) => (await jar.readCart()).filter((l) => l.bookId === bookId);
  const [aLine] = await lineOf(a.id);
  const [zLine] = await lineOf(z.id);
  expect(aLine?.quantity, 'setup: A line reads 1').toBe(1);
  expect(zLine?.quantity, 'setup: Z line reads 1').toBe(1);
  await shop.setStock(z, 0);

  // P-at-stock, then P-over-stock on A's line; P-zero-stock on Z's line. Every action first, the checks after.
  const atStock = await jar.changeLine(aLine.id, 3);
  const afterAtStock = (await lineOf(a.id)).map((l) => l.quantity);
  const overStock = await jar.changeLine(aLine.id, 4);
  const afterOverStock = (await lineOf(a.id)).map((l) => l.quantity);
  const zero = await jar.changeLine(zLine.id, 1);
  const afterZero = (await lineOf(z.id)).map((l) => l.quantity);

  expect.soft(atStock.status, 'Then 1: update to the stock (3) accepted').toBeLessThan(300);
  expect.soft(afterAtStock, 'Then 1: line reads 3').toEqual([3]);
  expect.soft(overStock.status, 'Then 2: update to stock+1 (4) refused with 400').toBe(400);
  expect.soft((overStock.body as { code?: string } | null)?.code, 'Then 2: code INSUFFICIENT_STOCK').toBe('INSUFFICIENT_STOCK');
  expect.soft(afterOverStock, 'Then 2: line keeps its last quantity 3').toEqual([3]);
  expect.soft(zero.status, 'Then 3: update to 1 on zero stock refused with 400').toBe(400);
  expect.soft((zero.body as { code?: string } | null)?.code, 'Then 3: code INSUFFICIENT_STOCK').toBe('INSUFFICIENT_STOCK');
  expect.soft(afterZero, 'Then 3: line keeps its quantity 1').toEqual([1]);
  expectStableErrorShape([overStock, zero], 'Then 2/3', true);
});
