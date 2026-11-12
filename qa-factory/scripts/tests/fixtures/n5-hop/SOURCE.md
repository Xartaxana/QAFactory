# n5-hop fixtures (t-2045 N5): the samples the `helper_declaration` and `import_forms` rows were verified on

A data row is written only when it was run on a real sample (t-1968 rule); these are the samples. Nothing here is invented except the
two small specs that call the real code, and each says so.

| fixture | original | what it proves |
|---|---|---|
| `pages/BasePage.ts` | `mybooks-stand/test-automation-framework/core/pages/BasePage.ts`, byte-identical (sha256 `d5102e4aed11bad7cc2e0c744ac081c3c7855186b193203f66fb778b49a9ca14`) | a class method with a check and no return type: `async expectUrl(pathPart: string) { await expect(this.page).toHaveURL(...); }`; a method with a return type: `byId(id: string): Locator { ... }` |
| `pages/CartPage.ts` | `.../core/pages/CartPage.ts`, byte-identical (sha256 `923903bfadf1f0009e7f15bddab03ecc5bd0002ccbba475fd0409bd7d59c20ba`) | page-object methods with `: Promise<void>` and a `get` accessor, none with a check; a return type holding braces (`readServerCart`) is not read - it is never a wrong hit |
| `arrow-const.spec.ts` | `.../tests/e2e/cart/cart-stale-tab.spec.ts` lines 40-44 (sha256 of the whole file `b59404d48b20a8df68e7e58937c24b966751248a9a30aad6c1aec2ee678a5018`), the arrow const `addOne` verbatim, hoisted out of the test body; the spec around it is written here | an arrow const with a block body and a check, called from a test whose own body asserts nothing |
| `page-object-method.spec.ts` | written here, calls the real `CartPage` / `BasePage` | the page-object hop, with and without the import that names the file |
| `jdk-imports.txt` | the import block of `java.base/java/util/FormatItem.java` in the JDK 21 `src.zip` (`lib/src.zip` of the JDK), eleven lines verbatim | the Java `import_forms` row on real Java: plain, nested-class, static-member and wildcard imports |
| `../local1-playwright/add-to-cart.spec.ts` | already in the repository (SOURCE.md there) | the TypeScript `import_forms` row on real imports (`from '../../../core/fixtures/cart.fixture'`) |

Not verified on a real sample, therefore NOT written: a wider Java `helper_declaration` (a helper returning a value, e.g. `boolean check(...)`)
and any C# `helper_declaration` / `import_forms` row. No real Java or C# test project was on this machine.
