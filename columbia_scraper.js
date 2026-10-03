(async () => {

const TOKEN = "__SHOPIFY_TOKEN__";

const ENDPOINT =
"https://columbia-sportswear-india.myshopify.com/api/2025-07/graphql.json";

const QUERY = `
query GetProducts($first:Int!, $after:String){

  search(
    query:"tag:*"
    types:PRODUCT
    first:$first
    after:$after
  ){

    edges{

      cursor

      node{

        ... on Product{

          id
          title

            handle
            featuredImage{
            url
            }

          variants(first:100){

            edges{

              node{

                sku
                barcode
                availableForSale
                
                price{
                  amount
                }

                compareAtPrice{
                  amount
                }

              }

            }

          }

        }

      }

    }

    pageInfo{
      hasNextPage
      endCursor
    }

  }

}
`;

window.output = [];

const progressStartedAt = Date.now();
window.updateProgress = function (progress) {
    const current = Number(progress.current || 0), total = Number(progress.total || 0);
    const elapsedSeconds = Math.max(0, (Date.now() - progressStartedAt) / 1000);
    const payload = {
        ...progress,
        current,
        total,
        elapsed_seconds: Math.round(elapsedSeconds),
        eta_seconds: current > 0 && total > current ? Math.round((elapsedSeconds / current) * (total - current)) : 0,
        updated_at: new Date().toISOString()
    };
    window.__SCRAPER_PROGRESS__ = payload;
    if (typeof window.updateScraperProgress === "function") {
        try {
            const res = window.updateScraperProgress(payload);
            if (res && typeof res.catch === "function") {
                res.catch(() => {});
            }
        } catch (_) {}
    }
};

const sleep = ms => new Promise(r => setTimeout(r, ms));
const randomDelay = () => 1200 + Math.floor(Math.random() * 1000);

let cursor = null;
let hasNextPage = true;
let page = 1;

while (hasNextPage) {
    console.log(`Fetching Page ${page} (cursor: ${cursor || "start"})...`);
    window.updateProgress({ stage: "Collecting Products", current: page, total: page + 1 });

    let json = null;
    let success = false;
    for (let attempt = 1; attempt <= 5; attempt++) {
        try {
            const response = await fetch(ENDPOINT, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Shopify-Storefront-Access-Token": TOKEN
                },
                body: JSON.stringify({
                    query: QUERY,
                    variables: {
                        first: 250,
                        after: cursor
                    }
                })
            });

            if (!response.ok) {
                console.warn(`HTTP ${response.status} on Columbia Page ${page}, attempt ${attempt}/5`);
                if (attempt < 5) {
                    const waitMs = attempt * 3000;
                    console.log(`Waiting ${waitMs}ms before retry...`);
                    await sleep(waitMs);
                    continue;
                }
                console.error(`HTTP error ${response.status} on page ${page} after 5 attempts`);
                break;
            }

            json = await response.json();
            if (json.errors) {
                console.warn(`GraphQL errors on page ${page}, attempt ${attempt}/5:`, json.errors);
                if (attempt < 5) {
                    await sleep(attempt * 2000);
                    continue;
                }
                console.error(`GraphQL errors persisted on page ${page}`);
                break;
            }

            success = true;
            break;
        } catch (fetchErr) {
            console.warn(`Network error on Columbia page ${page}, attempt ${attempt}/5:`, fetchErr);
            if (attempt < 5) {
                const waitMs = attempt * 3000;
                await sleep(waitMs);
                continue;
            }
            console.error(`Persistent network error on page ${page}:`, fetchErr);
            break;
        }
    }

    if (!success || !json) {
        console.error(`Stopping Columbia pagination at page ${page} due to persistent error.`);
        break;
    }

    const search = json.data?.search;
    const edges = search?.edges || [];
    for (const edge of edges) {
        const product = edge.node;
        for (const { node } of (product.variants?.edges || [])) {
            window.output.push({
                source: "columbia",
                product_id: product.id.split("/").pop(),
                sku: node.sku,
                ean: node.barcode,
                available: node.availableForSale,
                title: product.title,
                price: Number(node.price?.amount || 0),
                mrp: node.compareAtPrice
                    ? Number(node.compareAtPrice.amount)
                    : Number(node.price?.amount || 0),
                image_url: product.featuredImage?.url || "",
                url: "https://www.columbiasportswear.co.in/products/" + product.handle
            });
        }
    }

    console.log(`Page ${page}: fetched ${edges.length} products. Total SKUs so far: ${window.output.length}`);

    hasNextPage = Boolean(search?.pageInfo?.hasNextPage) && edges.length > 0;
    cursor = search?.pageInfo?.endCursor || (edges.length > 0 ? edges[edges.length - 1].cursor : null);
    page++;

    if (hasNextPage) {
        await sleep(randomDelay());
    }
}

const totalPages = Math.max(1, page - 1);
console.log(`Collected ${window.output.length} products across ${totalPages} pages`);
console.log("Done!");
console.log(window.output);
console.log("Total SKUs:", window.output.length);
window.updateProgress({ stage: "Completed", current: totalPages, total: totalPages });

// Download JSON

const output = {

    schema_version: 1,

    source: "columbia",

    scrape_date: new Date().toISOString().slice(0,10),

    scraped_at: new Date().toISOString(),

    products: window.output

};

const blob = new Blob(
    [
      JSON.stringify(output, null, 2)
    ],
    {
        type: "application/json"
    }
);

const url = URL.createObjectURL(blob);

const a = document.createElement("a");

a.href = url;
a.download = "columbia_products.json";

document.body.appendChild(a);

a.click();

document.body.removeChild(a);

URL.revokeObjectURL(url);

console.log("Download Complete!");
setTimeout(() => { try { window.close(); } catch (_) {} }, 1500);

})();
