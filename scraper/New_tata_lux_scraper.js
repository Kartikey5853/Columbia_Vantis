/**
 * New Tata CLiQ Luxury Columbia Scraper (With Offers & Stock / Quantity)
 * 
 * Features:
 * - Collects Columbia product catalog from Tata CLiQ Luxury search endpoint
 * - Fetches PDP HTML for size variants, pricing, and winning seller details
 * - Extracts stock & quantity (numerical stock count, boolean availability, winning seller stock)
 * - Fetches available offers (Bank offers, coupons, deals) for each product
 * - Emits progress to window.__SCRAPER_PROGRESS__ and window.updateScraperProgress
 * - Generates clean JSON schema including offers, variants, and stock
 */

(async () => {

    const SEARCH_TEXT =
        "Columbia:relevance:list:listId_3b2c31cb7dc142898a1f01694ec87d79";

    const PAGE_SIZE = 24;
    const LISTING_RETRIES = 3;
    const PDP_RETRIES = 3;
    const CONCURRENCY = 5;

    const LISTING_BASE =
        "https://cliqapi.tatacliq.com/cliq-api/v1/lux/search";

    const PDP_BASE =
        "https://luxury.tatacliq.com";

    const OFFER_BASE_URL =
        "https://www.tatacliq.com/marketplacewebservices";

    const sleep = ms =>
        new Promise(resolve => setTimeout(resolve, ms));

    const randomDelay = (min, max) =>
        min + Math.floor(Math.random() * (max - min + 1));

    const progressStartedAt = Date.now();

    window.updateProgress = function (progress) {
        const current = Number(progress.current || 0);
        const total = Number(progress.total || 0);
        const elapsedSeconds =
            Math.max(0, (Date.now() - progressStartedAt) / 1000);

        const payload = {
            ...progress,
            current,
            total,
            elapsed_seconds: Math.round(elapsedSeconds),
            eta_seconds:
                current > 0 && total > current
                    ? Math.round((elapsedSeconds / current) * (total - current))
                    : 0,
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

    function absoluteUrl(value) {
        if (!value) return "";
        if (value.startsWith("http://") || value.startsWith("https://")) return value;
        if (value.startsWith("//")) return "https:" + value;
        return PDP_BASE + (value.startsWith("/") ? value : "/" + value);
    }

    function numberOrNull(value) {
        if (value === null || value === undefined || value === "") return null;
        if (typeof value === "number") return Number.isFinite(value) ? value : null;
        const parsed = Number(String(value).replace(/[^0-9.-]/g, ""));
        return Number.isFinite(parsed) ? parsed : null;
    }

    function priceValue(value) {
        return numberOrNull(
            value?.value ??
            value?.doubleValue ??
            value?.rawValue ??
            value?.formattedValue
        );
    }

    function buildListingUrl(page) {
        const params = new URLSearchParams({
            isTextSearch: "false",
            isFilter: "false",
            isPwa: "true",
            channel: "web",
            typeID: "all",
            page: String(page),
            pageSize: String(PAGE_SIZE),
            searchText: SEARCH_TEXT,
            isSortFlow: "false",
            isSuggested: "false",
            isMDE: "true",
            test: "es.template.binning.qpsv4",
            qc: "false",
            isKeywordRedirect: "false",
            isKeywordRedirectEnabled: "false",
            isFilterDataRequired: "false",
            ad: "true"
        });
        return `${LISTING_BASE}?${params.toString()}`;
    }

    async function fetchListingPage(page) {
        const url = buildListingUrl(page);
        const response = await fetch(url, {
            headers: {
                "appplatform": "web",
                "appversion": "v1",
                "x-provider-id": "cliq-search",
                "Accept": "application/json"
            }
        });

        if (!response.ok) {
            throw new Error(`Listing HTTP ${response.status}`);
        }
        return response.json();
    }

    async function fetchPdpHtml(product) {
        const url = absoluteUrl(product.url);
        const response = await fetch(url, {
            headers: {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            }
        });

        if (!response.ok) {
            throw new Error(`PDP HTTP ${response.status}`);
        }
        return response.text();
    }

    function extractEmbeddedProductObject(html) {
        const marker = '"variantOptions":';
        let index = 0;
        while ((index = html.indexOf(marker, index)) !== -1) {
            let start = -1;
            let depth = 0;
            for (let i = index; i >= 0; i--) {
                const c = html[i];
                if (c === "}") depth++;
                else if (c === "{") {
                    if (depth === 0) {
                        start = i;
                        break;
                    }
                    depth--;
                }
            }

            if (start !== -1) {
                let depthCount = 0;
                let inStr = false;
                let esc = false;
                for (let i = start; i < html.length; i++) {
                    const c = html[i];
                    if (inStr) {
                        if (esc) esc = false;
                        else if (c === "\\") esc = true;
                        else if (c === '"') inStr = false;
                        continue;
                    }
                    if (c === '"') inStr = true;
                    else if (c === "{") depthCount++;
                    else if (c === "}") {
                        depthCount--;
                        if (depthCount === 0) {
                            try {
                                const parsed = JSON.parse(html.slice(start, i + 1));
                                if (parsed?.variantOptions || parsed?.variantGroup) {
                                    return parsed;
                                }
                            } catch (_) {}
                            break;
                        }
                    }
                }
            }
            index += marker.length;
        }
        return null;
    }

    function normalizeOffer(rawOffer, kind, currentSellingPrice) {
        const textContent =
            rawOffer?.offerHighlights ||
            rawOffer?.title ||
            rawOffer?.description ||
            rawOffer?.message ||
            "";

        // Extract code: check couponCode, voucherIdentifier (e.g. 'RBLTCL_TER' -> 'RBLTCL'), or regex
        const voucher = rawOffer?.voucherIdentifier || "";
        const voucherCode = voucher ? voucher.split("_")[0].toUpperCase() : "";
        const regexCodeMatch = textContent.match(/(?:coupon|code)\s*[:\-]?\s*([A-Z0-9]+)/i);
        const parsedCode =
            rawOffer?.couponCode ||
            rawOffer?.code ||
            rawOffer?.promoCode ||
            voucherCode ||
            (regexCodeMatch ? regexCodeMatch[1].toUpperCase() : "");

        // Extract min purchase amount
        const regexMin = textContent.match(/(?:min(?:imum)?\s*(?:purchase|spend|transaction)|on)\s*[:\-]?\s*Rs\.?\s*([\d,]+)/i);
        const minPurchase = numberOrNull(
            rawOffer?.minimumTransactionAmount ??
            rawOffer?.minTransactionAmount ??
            rawOffer?.minimumOrderValue ??
            rawOffer?.minPurchaseAmount ??
            (regexMin ? regexMin[1].replace(/,/g, "") : null)
        );

        // Extract max discount
        const regexMax = textContent.match(/max(?:imum)?\s*discount\s*[:\-]?\s*Rs\.?\s*([\d,]+)/i);
        const maxDiscount = numberOrNull(
            rawOffer?.maximumDiscount ??
            rawOffer?.maxDiscount ??
            rawOffer?.maxOfferDiscount ??
            (regexMax ? regexMax[1].replace(/,/g, "") : null)
        );

        // Extract discount percent
        const regexPct = textContent.match(/(\d+(?:\.\d+)?)\s*%/);
        const discountPercent = numberOrNull(
            rawOffer?.discountPercent ??
            rawOffer?.percentageDiscount ??
            (regexPct ? regexPct[1] : null)
        );

        // Extract discount amount
        const regexAmt = textContent.match(/off\s+on\s+([\d,]+)/i);
        const discountAmount = numberOrNull(
            rawOffer?.discountAmount ??
            rawOffer?.offerAmount ??
            rawOffer?.discountValue ??
            (regexAmt ? regexAmt[1].replace(/,/g, "") : null)
        );

        // Compute offer price if applicable
        let offerPrice = numberOrNull(rawOffer?.offerPrice);
        if (offerPrice === null && currentSellingPrice && currentSellingPrice > 0) {
            if (discountPercent && discountPercent > 0) {
                const calculated = currentSellingPrice - (currentSellingPrice * (discountPercent / 100));
                offerPrice = Math.max(0, Math.round(calculated));
            } else if (discountAmount && discountAmount > 0) {
                offerPrice = Math.max(0, Math.round(currentSellingPrice - discountAmount));
            }
        }

        // Issuer / Bank detection
        const issuerMatch = textContent.match(/\b(RBL|American Express|Amex|AU Bank|AU|IndusInd|ICICI|Kotak|Axis|HDFC|SBI|OneCard|IDFC)\b/i);
        const issuer = issuerMatch ? issuerMatch[0] : (rawOffer?.bankName || rawOffer?.issuer || rawOffer?.bank || "");

        // Card Type detection
        const cardTypeMatch = textContent.match(/\b(Credit Card Full Swipe|Credit Card EMI|Credit Card|Debit Card|EMI)\b/i);
        const cardType = cardTypeMatch ? cardTypeMatch[0] : (rawOffer?.cardType || rawOffer?.paymentType || "");

        return {
            kind,
            code: parsedCode,
            title:
                rawOffer?.title ||
                rawOffer?.offerTitle ||
                rawOffer?.offerName ||
                rawOffer?.heading ||
                rawOffer?.offerHighlights ||
                "",
            description:
                rawOffer?.description ||
                rawOffer?.offerDescription ||
                rawOffer?.message ||
                rawOffer?.details ||
                rawOffer?.offerHighlights ||
                "",
            offer_price: offerPrice,
            issuer,
            card_type: cardType,
            payment_network: rawOffer?.cardNetwork || rawOffer?.network || "",
            discount_percent: discountPercent,
            discount_amount: discountAmount,
            minimum_transaction_amount: minPurchase,
            maximum_discount: maxDiscount,
            valid_from:
                rawOffer?.offerStartDate ||
                rawOffer?.startDateAndTime ||
                rawOffer?.startDate ||
                "",
            validity:
                rawOffer?.validity ||
                rawOffer?.validTill ||
                rawOffer?.endDate ||
                rawOffer?.endDateAndTime ||
                rawOffer?.offerEndDate ||
                "",
            terms_url:
                rawOffer?.termsUrl ||
                rawOffer?.tncUrl ||
                rawOffer?.termsAndConditionsUrl ||
                ""
        };
    }

    function normalizeOffers(data, currentSellingPrice) {
        if (!data || typeof data !== "object") return [];
        const groups = [
            { kind: "bank_offer", values: data.bankofferList },
            { kind: "deal", values: data.dealOfferCalloutList },
            { kind: "coupon", values: data.impulseOfferCalloutList },
            { kind: "other", values: data.otherOffers }
        ];

        const offers = [];
        for (const group of groups) {
            if (!Array.isArray(group.values)) continue;
            for (const raw of group.values) {
                offers.push(normalizeOffer(raw, group.kind, currentSellingPrice));
            }
        }
        return offers;
    }

    async function fetchLuxuryProductOffers(productId, sellerId, categoryCode, brandCode, currentSellingPrice) {
        try {
            if (!sellerId || !categoryCode) return [];
            const params = new URLSearchParams({
                isPwa: "true",
                channel: "web",
                sellerId: String(sellerId),
                categoryCode: String(categoryCode),
                brandCode: String(brandCode || ""),
                updatedFlag: "true",
                neuPassFlag: "true",
                neuPassSLPFlag: "true"
            });

            // Primary endpoint: Tata CLiQ Luxury Marketplace endpoint (preserves exact uppercase product code)
            const upperId = String(productId).toUpperCase();
            const luxUrl = `https://luxury.tatacliq.com/marketplacewebservices/v2/lux/products/${upperId}/pdpOfferCallout?${params.toString()}`;

            let response = await fetch(luxUrl, {
                headers: { "Accept": "application/json" }
            });

            // Fallback to standard mpl endpoint if luxury returns non-200
            if (!response.ok) {
                const mplUrl = `${OFFER_BASE_URL}/v2/mpl/products/${String(productId).toLowerCase()}/pdpOfferCallout?${params.toString()}`;
                response = await fetch(mplUrl, {
                    headers: { "Accept": "application/json" }
                });
            }

            if (!response.ok) return [];
            const data = await response.json();
            return normalizeOffers(data, currentSellingPrice);
        } catch (_) {
            return [];
        }
    }

    function parseLuxuryVariants(html, productObject) {
        let rawVariants = Array.isArray(productObject?.variantOptions) ? productObject.variantOptions : [];
        if (rawVariants.length === 0 && Array.isArray(productObject?.variantGroup)) {
            for (const group of productObject.variantGroup) {
                const sizes = Array.isArray(group?.sizeOptions) ? group.sizeOptions : [];
                for (const s of sizes) {
                    rawVariants.push({
                        colorlink: group.colorLink || {},
                        sizelink: s
                    });
                }
            }
        }

        const variants = [];
        for (const v of rawVariants) {
            const sizeLink = v?.sizelink || v?.sizeLink || v || {};
            const colorLink = v?.colorlink || v?.colorLink || {};
            const rawStock = sizeLink?.stockCount ?? null;
            const isAvail = sizeLink?.isAvailable === true || (rawStock !== null && Number(rawStock) > 0);
            const stockVal = numberOrNull(rawStock);

            variants.push({
                size: String(sizeLink?.size || sizeLink?.brandSize || ""),
                color: String(colorLink?.color || ""),
                sku: String(sizeLink?.productCode || ""),
                available: isAvail,
                quantity: stockVal !== null ? stockVal : (isAvail ? true : false),
                stock: stockVal !== null ? stockVal : (isAvail ? true : false),
                url: absoluteUrl(sizeLink?.url || colorLink?.colorurl || "")
            });
        }
        return variants;
    }

    const cleanProducts = [];
    window.__TATA_LUX_UNSAVED_LISTINGS__ = window.__TATA_LUX_UNSAVED_LISTINGS__ || [];
    window.drainUnsavedListings = function () {
        const u = window.__TATA_LUX_UNSAVED_LISTINGS__ || [];
        window.__TATA_LUX_UNSAVED_LISTINGS__ = [];
        return u;
    };

    function processLuxuryListing(searchResult, pageNumber = 0) {
        const scrapedAt = new Date().toISOString();
        const pageItems = [];
        for (const item of searchResult) {
            const p = {
                source: "tatacliq_luxury",
                product_id: String(item.productId || ""),
                sku: "",
                ean: "",
                available: item.inStockFlag === true,
                title: item.productname || "",
                color: item.productColor || "",
                price: priceValue(item.price?.sellingPrice) ?? 0,
                mrp: priceValue(item.price?.mrpPrice) ?? priceValue(item.price?.sellingPrice) ?? 0,
                image_url: absoluteUrl(item.imageURL),
                url: absoluteUrl(item.webURL),
                variants: [],
                offers: [],
                max_quantity_allowed: null,
                seller_available_stock: null,
                stock: item.inStockFlag === true ? true : false,
                scraped_at: scrapedAt
            };
            cleanProducts.push(p);
            pageItems.push(p);
        }
        if (typeof window.__TATA_LUX_UNSAVED_LISTINGS__ !== "undefined") {
            window.__TATA_LUX_UNSAVED_LISTINGS__.push({
                page: pageNumber,
                products: pageItems
            });
        }
        return pageItems;
    }

    console.log("Fetching first luxury listing page...");
    const firstPage = await fetchListingPage(0);
    const totalPages = Number(firstPage?.pagination?.totalPages || 1);
    const totalResults = Number(firstPage?.pagination?.totalResults || 0);

    processLuxuryListing(firstPage.searchresult || [], 0);

    updateProgress({
        stage: "Collecting Products",
        current: 1,
        total: totalPages
    });

    for (let p = 1; p < totalPages; p++) {
        let success = false;
        for (let attempt = 1; attempt <= LISTING_RETRIES; attempt++) {
            try {
                const data = await fetchListingPage(p);
                processLuxuryListing(data.searchresult || [], p);
                updateProgress({
                    stage: "Collecting Products",
                    current: p + 1,
                    total: totalPages
                });
                success = true;
                break;
            } catch (err) {
                await sleep(3000);
            }
        }
        await sleep(randomDelay(1000, 2000));
    }

    // If running in listings_only phase, exit cleanly after completing Phase 1
    if (typeof window !== "undefined" && window.__PHASE__ === "listings_only") {
        console.log(`[TATA LUX LISTINGS] Phase 1 listings complete (${cleanProducts.length} products). Stopping before Phase 2.`);
        updateProgress({ stage: "Listings Complete", current: cleanProducts.length, total: cleanProducts.length });
        window.__LISTINGS_DONE__ = true;
        window.__SCRAPER_DONE__ = true;
        return {
            total_products: cleanProducts.length,
            products: cleanProducts
        };
    }

    let nextIndex = 0;
    let completed = 0;
    let totalVariants = 0;

    async function luxuryWorker(workerId) {
        while (true) {
            const index = nextIndex++;
            if (index >= cleanProducts.length) break;

            const product = cleanProducts[index];
            if (!product.url) {
                completed++;
                updateProgress({
                    stage: "Collecting Variants",
                    current: completed,
                    total: cleanProducts.length
                });
                continue;
            }

            try {
                const html = await fetchPdpHtml(product);
                const embedded = extractEmbeddedProductObject(html);

                // Extract variants
                product.variants = parseLuxuryVariants(html, embedded);
                totalVariants += product.variants.length;

                // Extract seller & stock
                const sellerId =
                    embedded?.winningSellerID ||
                    embedded?.winningSellerCode ||
                    (html.match(/"winningSellerID"\s*:\s*"?([^\",]+)"?/)?.[1]) ||
                    "";

                const sellerStock =
                    numberOrNull(embedded?.winningSellerAvailableStock) ??
                    numberOrNull(html.match(/"winningSellerAvailableStock"\s*:\s*"?([0-9]+)"?/)?.[1]);

                product.seller_available_stock = sellerStock;
                product.max_quantity_allowed =
                    numberOrNull(embedded?.maxQuantityAllowed) ??
                    numberOrNull(html.match(/"maxQuantityAllowed"\s*:\s*"?([0-9]+)"?/)?.[1]);

                product.stock =
                    sellerStock !== null
                        ? sellerStock
                        : (embedded?.allOOStock === false ? true : (product.available ? true : false));

                // Extract brand & category codes for offers
                const brandURL = embedded?.brandURL || html.match(/"brandURL"\s*:\s*"([^\"]+)"/)?.[1] || "";
                const brandCode = embedded?.brandCode || brandURL.split("-").pop()?.toUpperCase() || "";

                const hierarchy = Array.isArray(embedded?.categoryHierarchy) ? embedded.categoryHierarchy : [];
                const catCode =
                    hierarchy.length ? hierarchy[hierarchy.length - 1]?.category_id :
                    embedded?.productCategoryId ||
                    (html.match(/"category_id"\s*:\s*"([^\"]+)"/)?.[1]) || "";

                // Fetch Offers
                product.offers = await fetchLuxuryProductOffers(
                    product.product_id,
                    sellerId,
                    catCode,
                    brandCode,
                    product.price
                );
            } catch (err) {
                product.variants = [];
                product.offers = [];
            }

            completed++;
            updateProgress({
                stage: "Collecting Variants",
                current: completed,
                total: cleanProducts.length
            });

            console.log(
                `[Lux Worker ${workerId}] ${completed}/${cleanProducts.length}` +
                ` | Product ${product.product_id}` +
                ` | Variants: ${product.variants.length}` +
                ` | Offers: ${product.offers.length}` +
                ` | Stock: ${product.seller_available_stock ?? product.stock}`
            );

            await sleep(800 + Math.random() * 800);
        }
    }

    console.log(`Extracting luxury details/offers with ${CONCURRENCY} workers...`);
    updateProgress({
        stage: "Collecting Variants",
        current: 0,
        total: cleanProducts.length
    });

    await Promise.all(
        Array.from({ length: CONCURRENCY }, (_, i) => luxuryWorker(i + 1))
    );

    const output = {
        schema_version: 2,
        source: "tatacliq_luxury",
        scrape_date: new Date().toISOString().slice(0, 10),
        scraped_at: new Date().toISOString(),
        expected_products: totalResults,
        total_products: cleanProducts.length,
        total_variants: totalVariants,
        average_variants_per_product: Number(
            (totalVariants / Math.max(cleanProducts.length, 1)).toFixed(2)
        ),
        products: cleanProducts
    };

    if (typeof window !== "undefined") {
        window.__FINAL_RESULT__ = output;
        window.__SCRAPER_DONE__ = true;
    }

    if (typeof document !== "undefined" && document.createElement) {
        try {
            const blob = new Blob([JSON.stringify(output, null, 2)], {
                type: "application/json"
            });
            const downloadUrl = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = downloadUrl;
            link.download = "tatacliq_luxury_columbia_products_with_offers.json";
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(downloadUrl);
        } catch (_) {}
    }

    updateProgress({
        stage: "Completed",
        current: cleanProducts.length,
        total: cleanProducts.length
    });

    console.log("LUXURY SCRAPE COMPLETE:", output.total_products, "products,", output.total_variants, "variants.");
    return output;
})();
