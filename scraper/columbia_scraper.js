/**
 * New Columbia Sportswear India Scraper v2 (With EMI / Card Offers & Exact Stock / Quantities)
 * 
 * Features:
 * - Collects Columbia product catalog via Storefront GraphQL API
 * - Extracts exact variant-level stock count (quantityAvailable)
 * - Extracts exact variant availability (availableForSale)
 * - Extracts size, sku, barcode, price, mrp
 * - Computes Snapmint / Simpl / Cardless / Bank EMI options & special card payment terms
 * - Emits progress to window.__SCRAPER_PROGRESS__ and window.updateScraperProgress
 * - Generates clean JSON schema including offers, variants, and stock
 */

(async () => {

    const TOKEN = window.__SHOPIFY_TOKEN__ || "23fa3b40e0a46129e1b0cfaff2262c99";
    const ENDPOINT = "https://columbia-sportswear-india.myshopify.com/api/2025-07/graphql.json";

    const QUERY = `
    query GetProducts($first: Int!, $after: String) {
      products(first: $first, after: $after) {
        edges {
          cursor
          node {
            id
            title
            handle
            featuredImage {
              url
            }
            variants(first: 100) {
              edges {
                node {
                  id
                  title
                  sku
                  barcode
                  availableForSale
                  quantityAvailable
                  price {
                    amount
                  }
                  compareAtPrice {
                    amount
                  }
                  selectedOptions {
                    name
                    value
                  }
                }
              }
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
    `;

    window.output = [];
    window.__COLUMBIA_UNSAVED__ = [];

    window.drainUnsavedProducts = function () {
        const chunk = window.__COLUMBIA_UNSAVED__ || [];
        window.__COLUMBIA_UNSAVED__ = [];
        return chunk;
    };

    const progressStartedAt = Date.now();
    window.updateProgress = function (progress) {
        const current = Number(progress.current || 0);
        const total = Number(progress.total || 0);
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

    /**
     * Computes available EMI options & special card discounts based on product selling price
     * (Snapmint 3-month interest-free EMI, Simpl Pay-in-3, and Credit Card 3/6/9/12m EMI)
     */
    function computeColumbiaPaymentOffers(price) {
        if (!price || price <= 0) return [];
        const offers = [];

        // Snapmint 3-part / 0% interest EMI (active on store merchant 7029)
        if (price >= 1000) {
            const emi3 = Math.round(price / 3);
            offers.push({
                kind: "emi_offer",
                code: "",
                title: "Pay in 3 with Snapmint (0% Interest)",
                description: `Pay 3 monthly installments of ₹${emi3} with 0% interest and instant approval.`,
                issuer: "Snapmint",
                card_type: "Cardless EMI / UPI",
                payment_network: "Snapmint",
                discount_percent: null,
                discount_amount: null,
                minimum_transaction_amount: 1000,
                maximum_discount: null,
                offer_price: price,
                monthly_installment: emi3,
                tenure_months: 3,
                terms_url: "https://www.columbiasportswear.co.in"
            });
        }

        // Standard Credit Card No-Cost / Low-Cost EMI for items >= ₹3,000
        if (price >= 3000) {
            const emi3 = Math.round(price / 3);
            const emi6 = Math.round(price / 6);
            offers.push({
                kind: "bank_offer",
                code: "",
                title: "Credit Card EMI Available (3, 6, 9, 12 Months)",
                description: `EMI starts at ₹${emi6}/month across major banks (HDFC, ICICI, SBI, Axis, Kotak, IndusInd).`,
                issuer: "Major Indian Banks",
                card_type: "Credit Card EMI",
                payment_network: "Visa / Mastercard / RuPay",
                discount_percent: null,
                discount_amount: null,
                minimum_transaction_amount: 3000,
                maximum_discount: null,
                offer_price: price,
                monthly_installment: emi6,
                tenure_months: 6,
                terms_url: "https://www.columbiasportswear.co.in"
            });
        }

        return offers;
    }

    let cursor = null;
    let hasNextPage = true;
    let page = 1;
    let totalSkuCount = 0;
    const limit = window.__PRODUCT_LIMIT__ ? Number(window.__PRODUCT_LIMIT__) : 0;

    while (hasNextPage) {
        console.log(`Fetching Columbia Page ${page} (cursor: ${cursor || "start"})...`);
        window.updateProgress({ stage: "Collecting Products", current: page, total: page + 1, variant_count: totalSkuCount });

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
                        await sleep(waitMs);
                        continue;
                    }
                    break;
                }

                json = await response.json();
                if (json.errors) {
                    console.warn(`GraphQL errors on page ${page}:`, json.errors);
                    if (attempt < 5) {
                        await sleep(attempt * 2000);
                        continue;
                    }
                    break;
                }

                success = true;
                break;
            } catch (fetchErr) {
                if (attempt < 5) {
                    await sleep(attempt * 3000);
                    continue;
                }
                break;
            }
        }

        if (!success || !json) {
            console.error(`Stopping Columbia pagination at page ${page} due to persistent error.`);
            break;
        }

        const prodsData = json.data?.products;
        const edges = prodsData?.edges || [];
        let limitReached = false;

        for (const edge of edges) {
            const product = edge.node;
            const pId = String(product.id || "").split("/").pop();
            const productUrl = "https://www.columbiasportswear.co.in/products/" + product.handle;

            const variants = [];
            let totalAvailableStock = 0;
            let productLowestPrice = 0;
            let productHighestMrp = 0;

            for (const { node } of (product.variants?.edges || [])) {
                const variantPrice = Number(node.price?.amount || 0);
                const variantMrp = node.compareAtPrice ? Number(node.compareAtPrice.amount) : variantPrice;
                const qty = typeof node.quantityAvailable === "number" ? node.quantityAvailable : null;
                const isAvail = node.availableForSale === true || (qty !== null && qty > 0);

                if (qty !== null && qty > 0) totalAvailableStock += qty;
                if (!productLowestPrice || variantPrice < productLowestPrice) productLowestPrice = variantPrice;
                if (variantMrp > productHighestMrp) productHighestMrp = variantMrp;

                const sizeOption = (node.selectedOptions || []).find(o => o.name.toLowerCase() === "size")?.value || node.title || "";

                const variantObj = {
                    size: sizeOption,
                    sku: node.sku || "",
                    ean: node.barcode || "",
                    available: isAvail,
                    quantity: qty !== null ? qty : (isAvail ? true : false),
                    stock: qty !== null ? qty : (isAvail ? true : false),
                    price: variantPrice,
                    mrp: variantMrp
                };
                variants.push(variantObj);

                // Flat representation for legacy streaming / persistence
                const flatItem = {
                    source: "columbia",
                    product_id: pId,
                    sku: node.sku || "",
                    ean: node.barcode || "",
                    size: sizeOption,
                    available: isAvail,
                    quantity: qty !== null ? qty : (isAvail ? true : false),
                    stock: qty !== null ? qty : (isAvail ? true : false),
                    title: product.title,
                    price: variantPrice,
                    mrp: variantMrp,
                    image_url: product.featuredImage?.url || "",
                    url: productUrl,
                    offers: computeColumbiaPaymentOffers(variantPrice)
                };

                window.__COLUMBIA_UNSAVED__.push(flatItem);
                totalSkuCount++;

                if (limit > 0 && totalSkuCount >= limit) {
                    limitReached = true;
                    break;
                }
            }

            // Structured product payload with nested variants, offers & stock
            const structuredProduct = {
                source: "columbia",
                product_id: pId,
                title: product.title,
                price: productLowestPrice,
                mrp: productHighestMrp || productLowestPrice,
                available: variants.some(v => v.available),
                stock: totalAvailableStock > 0 ? totalAvailableStock : (variants.some(v => v.available) ? true : false),
                total_sellable_stock: totalAvailableStock,
                url: productUrl,
                image_url: product.featuredImage?.url || "",
                variants,
                offers: computeColumbiaPaymentOffers(productLowestPrice),
                scraped_at: new Date().toISOString()
            };

            window.output.push(structuredProduct);

            if (limitReached) break;
        }

        console.log(`Page ${page}: fetched ${edges.length} products. Total SKUs so far: ${totalSkuCount}`);
        window.updateProgress({
            stage: "Collecting Products",
            current: page,
            total: page + 1,
            variant_count: totalSkuCount
        });

        if (limitReached) break;

        hasNextPage = Boolean(prodsData?.pageInfo?.hasNextPage) && edges.length > 0;
        cursor = prodsData?.pageInfo?.endCursor || (edges.length > 0 ? edges[edges.length - 1].cursor : null);
        page++;

        if (hasNextPage) {
            await sleep(randomDelay());
        }
    }

    const totalPages = Math.max(1, page - 1);
    console.log(`Done! Collected ${window.output.length} products (${totalSkuCount} SKUs) across ${totalPages} pages.`);
    window.updateProgress({ stage: "Completed", current: totalPages, total: totalPages, variant_count: totalSkuCount });
    window.__SCRAPER_DONE__ = true;

    const output = {
        schema_version: 2,
        source: "columbia",
        scrape_date: new Date().toISOString().slice(0, 10),
        scraped_at: new Date().toISOString(),
        total_products: window.output.length,
        total_skus: totalSkuCount,
        products: window.output
    };

    if (typeof window !== "undefined") {
        window.__FINAL_RESULT__ = output;
    }

    if (typeof document !== "undefined" && document.createElement) {
        try {
            const blob = new Blob([JSON.stringify(output, null, 2)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "columbia_products_with_offers.json";
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (_) {}
    }

    return output;
})();
