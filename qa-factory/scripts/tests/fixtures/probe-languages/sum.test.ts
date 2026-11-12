import { sum } from './sum';

describe('calc', () => {
  test('adds', () => {
    // expect(sum(0, 0)).toBe(1);  -- a comment: never the first assertion
    expect(sum(1, 2)).toBe(3);
  });

  it('is concise', () => expect(sum(1, 1)).toBe(2));
});
