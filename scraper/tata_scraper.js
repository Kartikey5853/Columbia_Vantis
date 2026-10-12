/**
 * New Tata CLiQ Columbia Scraper (With Offers & Stock / Quantity)
 * 
 * Features:
 * - Collects Columbia product catalog from Tata CLiQ search BFF
 * - Fetches product details and all variants
 * - Extracts available offers (Bank offers, coupons, deals, impulse discounts) with code, discount, offer price, min purchase, validity
 * - Extracts stock & quantity (stock count / boolean availability / winning seller available stock / max quantity)
 * - Emits progress to window.__SCRAPER_PROGRESS__ and window.updateScraperProgress for headless runners
 * - Generates clean JSON schema including offers, variants, and stock
 */

(async () => {
    const sleep = ms =>
        new Promise(resolve => setTimeout(resolve, ms));

    const randomDelay = () =>
        1500 + Math.floor(Math.random() * 2000);

    const PAGE_SIZE = 40;
    const CONCURRENCY = 5;

    const BASE_URL =
        "https://searchbff.tatacliq.com/products/mpl/search";

    const MCVID =
        "17842193248194609071977202052631231983";

    const DETAIL_URL = productId =>
        `https://www.tatacliq.com/marketplacewebservices/v2/mpl/products/${String(productId).toLowerCase()}?isPwa=true&isMDE=true&isDynamicVar=true`;

    const OFFER_BASE_URL =
        "https://www.tatacliq.com/marketplacewebservices";

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
                    ? Math.round(
                        (elapsedSeconds / current) *
                        (total - current)
                    )
                    : 0,
            updated_at: new Date().toISOString()
        };

        window.__SCRAPER_PROGRESS__ = payload;

        if (typeof window.updateScraperProgress === "function") {
            try {
                const result =
                    window.updateScraperProgress(payload);

                if (
                    result &&
                    typeof result.catch === "function"
                ) {
                    result.catch(() => {});
                }
            }
            catch (_) {}
        }
    };

    function buildUrl(page) {
        const params = new URLSearchParams({
            searchText:
                "columbia:relevance:inStockFlag:true",
            isKeywordRedirect: "false",
            isKeywordRedirectEnabled: "false",
            channel: "WEB",
            isMDE: "true",
            isTextSearch: "false",
            isFilter: "false",
            qc: "false",
            test: "invizbff.qpsv3-inviz.ab",
            page: String(page),
            mcvid: MCVID,
            customerId: "",
            isSuggested: "false",
            isFilterDataRequired: "true",
            isPwa: "true",
            pageSize: String(PAGE_SIZE),
            typeID: "all"
        });

        return `${BASE_URL}?${params.toString()}`;
    }

    async function fetchJson(url) {
        const response = await fetch(
            url,
            {
                headers: {
                    Accept: "application/json"
                }
            }
        );

        if (!response.ok) {
            throw new Error(
                `HTTP ${response.status}`
            );
        }

        return response.json();
    }

    async function fetchPage(page) {
        return fetchJson(buildUrl(page));
    }

    function numberOrNull(value) {
        if (
            value === null ||
            value === undefined ||
            value === ""
        ) {
            return null;
        }

        if (typeof value === "number") {
            return Number.isFinite(value)
                ? value
                : null;
        }

        const parsed =
            Number(
                String(value).replace(
                    /[^0-9.-]/g,
                    ""
                )
            );

        return Number.isFinite(parsed)
            ? parsed
            : null;
    }

    function priceValue(value) {
        return numberOrNull(
            value?.value ??
            value?.doubleValue ??
            value?.rawValue ??
            value?.formattedValue
        );
    }

    function absoluteUrl(value) {
        if (!value) {
            return "";
        }

        if (value.startsWith("http://")) {
            return value;
        }

        if (value.startsWith("https://")) {
            return value;
        }

        if (value.startsWith("//")) {
            return "https:" + value;
        }

        return "https://www.tatacliq.com" +
            (value.startsWith("/")
                ? value
                : "/" + value);
    }

    function brandCodeFromDetail(detail) {
        if (detail?.brandCode) {
            return String(detail.brandCode).trim().toUpperCase();
        }
        return String(detail?.brandURL || "")
            .split("-")
            .filter(Boolean)
            .pop()
            ?.toUpperCase() || "";
    }

    function categoryCodeFromDetail(detail) {
        if (detail?.productCategoryId) {
            return String(detail.productCategoryId).trim();
        }
        if (detail?.categoryL4Code) {
            return String(detail.categoryL4Code).trim();
        }
        const hierarchy =
            Array.isArray(detail?.categoryHierarchy)
                ? detail.categoryHierarchy
                : [];

        return hierarchy.length
            ? hierarchy[hierarchy.length - 1]?.category_id || ""
            : "";
    }

    function normalizeOffer(rawOffer, kind, currentSellingPrice) {
        const discountAmount = numberOrNull(
            rawOffer?.discountAmount ??
            rawOffer?.offerAmount ??
            rawOffer?.discountValue ??
            rawOffer?.maxOfferDiscount
        );

        const discountPercent = numberOrNull(
            rawOffer?.discountPercent ??
            rawOffer?.percentageDiscount
        );

        const minPurchase = numberOrNull(
            rawOffer?.minimumTransactionAmount ??
            rawOffer?.minTransactionAmount ??
            rawOffer?.minimumOrderValue ??
            rawOffer?.minPurchaseAmount
        );

        let offerPrice = numberOrNull(rawOffer?.offerPrice);
        if (offerPrice === null && currentSellingPrice && currentSellingPrice > 0) {
            if (discountPercent && discountPercent > 0) {
                const calculated = currentSellingPrice - (currentSellingPrice * (discountPercent / 100));
                offerPrice = Math.max(0, Math.round(calculated));
            } else if (discountAmount && discountAmount > 0) {
                offerPrice = Math.max(0, Math.round(currentSellingPrice - discountAmount));
            }
        }

        return {
            kind,

            code:
                rawOffer?.couponCode ||
                rawOffer?.code ||
                rawOffer?.promoCode ||
                "",

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

            offer_price:
                offerPrice,

            issuer:
                rawOffer?.bankName ||
                rawOffer?.issuer ||
                rawOffer?.bank ||
                rawOffer?.partnerName ||
                "",

            card_type:
                rawOffer?.cardType ||
                rawOffer?.paymentType ||
                "",

            payment_network:
                rawOffer?.cardNetwork ||
                rawOffer?.network ||
                "",

            discount_percent:
                discountPercent,

            discount_amount:
                discountAmount,

            minimum_transaction_amount:
                minPurchase,

            maximum_discount:
                numberOrNull(
                    rawOffer?.maximumDiscount ??
                    rawOffer?.maxDiscount ??
                    rawOffer?.maxOfferDiscount
                ),

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
        if (
            !data ||
            typeof data !== "object"
        ) {
            return [];
        }

        const groups = [
            {
                kind: "bank_offer",
                values: data.bankofferList
            },
            {
                kind: "deal",
                values: data.dealOfferCalloutList
            },
            {
                kind: "coupon",
                values: data.impulseOfferCalloutList
            },
            {
                kind: "other",
                values: data.otherOffers
            }
        ];

        const offers = [];

        for (const group of groups) {
            if (!Array.isArray(group.values)) {
                continue;
            }

            for (const rawOffer of group.values) {
                offers.push(
                    normalizeOffer(
                        rawOffer,
                        group.kind,
                        currentSellingPrice
                    )
                );
            }
        }

        return offers;
    }

    async function fetchProductOffers(detail, productId, currentSellingPrice) {
        try {
            const sellerId =
                detail?.winningSellerID ||
                detail?.winningSellerCode ||
                "";

            const categoryCode =
                categoryCodeFromDetail(detail);

            const brandCode =
                brandCodeFromDetail(detail);

            if (
                !sellerId ||
                !categoryCode
            ) {
                return [];
            }

            const params =
                new URLSearchParams({
                    sellerId: String(sellerId),
                    categoryCode: String(categoryCode),
                    neuPassSLPFlag: "true",
                    brandCode,
                    channel: "web",
                    updatedFlag: "true",
                    neuPassFlag: "true"
                });

            const url =
                `${OFFER_BASE_URL}/v2/mpl/products/` +
                `${String(productId).toLowerCase()}` +
                `/pdpOfferCallout?${params.toString()}`;

            const data =
                await fetchJson(url);

            return normalizeOffers(data, currentSellingPrice);
        }
        catch (error) {
            console.warn(
                "Offer request failed:",
                productId,
                error.message
            );

            return [];
        }
    }

    async function fetchVariants(productId, currentSellingPrice) {
        try {
            const detail =
                await fetchJson(
                    DETAIL_URL(productId)
                );

            const rawVariants =
                Array.isArray(detail.variantOptions)
                    ? detail.variantOptions
                    : [];

            const variants =
                rawVariants.map(variant => {
                    const sizeLink =
                        variant?.sizelink ||
                        variant?.sizeLink ||
                        {};

                    const colorLink =
                        variant?.colorlink ||
                        variant?.colorLink ||
                        {};

                    const rawStock =
                        sizeLink.stockCount ??
                        null;

                    const isAvailable =
                        sizeLink.isAvailable === true ||
                        (rawStock !== null && Number(rawStock) > 0);

                    const stockCountVal =
                        numberOrNull(rawStock);

                    return {
                        size:
                            sizeLink.size ||
                            sizeLink.brandSize ||
                            "",

                        color:
                            colorLink.color ||
                            "",

                        sku:
                            sizeLink.productCode ||
                            "",

                        available:
                            isAvailable,

                        quantity:
                            stockCountVal !== null
                                ? stockCountVal
                                : (isAvailable ? true : false),

                        stock:
                            stockCountVal !== null
                                ? stockCountVal
                                : (isAvailable ? true : false),

                        url:
                            absoluteUrl(
                                sizeLink.url
                            )
                    };
                });

            const offers =
                await fetchProductOffers(
                    detail,
                    productId,
                    currentSellingPrice
                );

            const sellerStock =
                numberOrNull(detail.winningSellerAvailableStock);

            return {
                variants,

                offers,

                max_quantity_allowed:
                    numberOrNull(
                        detail.maxQuantityAllowed
                    ),

                seller_available_stock:
                    sellerStock,

                stock:
                    sellerStock !== null
                        ? sellerStock
                        : (detail.allOOStock === false ? true : false),

                detail
            };
        }
        catch (error) {
            console.warn(
                "Detail request failed:",
                productId,
                error.message
            );

            return {
                variants: [],
                offers: [],
                max_quantity_allowed: null,
                seller_available_stock: null,
                stock: null,
                detail: null
            };
        }
    }

    const cleanProducts = [];
    window.__TATA_UNSAVED_LISTINGS__ = window.__TATA_UNSAVED_LISTINGS__ || [];
    window.drainUnsavedListings = function () {
        const u = window.__TATA_UNSAVED_LISTINGS__ || [];
        window.__TATA_UNSAVED_LISTINGS__ = [];
        return u;
    };

    function processProducts(products, pageNumber = 0) {
        const scrapedAt =
            new Date().toISOString();
        const pageItems = [];

        for (const product of products) {
            const item = {
                source: "tatacliq",

                product_id:
                    String(product.productId || ""),

                sku: "",

                ean: "",

                available:
                    product.inStockFlag === true,

                title:
                    product.productname || "",

                color:
                    product.productColor || "",

                price:
                    priceValue(
                        product.price?.sellingPrice
                    ) ?? 0,

                mrp:
                    priceValue(
                        product.price?.mrpPrice
                    ) ??
                    priceValue(
                        product.price?.sellingPrice
                    ) ??
                    0,

                image_url:
                    absoluteUrl(
                        product.imageURL
                    ),

                url:
                    absoluteUrl(
                        product.webURL
                    ),

                variants: [],

                offers: [],

                max_quantity_allowed: null,

                seller_available_stock: null,

                stock:
                    product.inStockFlag === true ? true : false,

                scraped_at: scrapedAt
            };
            cleanProducts.push(item);
            pageItems.push(item);
        }

        if (typeof window.__TATA_UNSAVED_LISTINGS__ !== "undefined") {
            window.__TATA_UNSAVED_LISTINGS__.push({
                page: pageNumber,
                products: pageItems
            });
        }
        return pageItems;
    }

    console.log("Fetching first page...");

    const first =
        await fetchPage(0);

    const totalPages =
        Number(
            first?.pagination?.totalPages || 1
        );

    const totalResults =
        Number(
            first?.pagination?.totalResults || 0
        );

    processProducts(
        first.searchresult || [],
        0
    );

    updateProgress({
        stage: "Collecting Products",
        current: 1,
        total: totalPages
    });

    for (
        let page = 1;
        page < totalPages;
        page++
    ) {
        let success = false;

        for (
            let attempt = 1;
            attempt <= 3;
            attempt++
        ) {
            try {
                console.log(
                    `Listing Page ${page + 1}/${totalPages}` +
                    ` Attempt ${attempt}`
                );

                const data =
                    await fetchPage(page);

                processProducts(
                    data.searchresult || [],
                    page
                );

                updateProgress({
                    stage: "Collecting Products",
                    current: page + 1,
                    total: totalPages
                });

                success = true;
                break;
            }
            catch (error) {
                console.warn(
                    "Listing retry failed:",
                    error.message
                );

                await sleep(5000);
            }
        }

        if (!success) {
            console.warn(
                `Skipped page ${page + 1}`
            );
        }

        await sleep(
            randomDelay()
        );
    }

    // If running in listings_only phase, exit cleanly after completing Phase 1
    if (typeof window !== "undefined" && window.__PHASE__ === "listings_only") {
        console.log(`[tata](checkpoint) Phase 1 listings complete (${cleanProducts.length} products). Stopping before Phase 2.`);
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
    let failedVariants = 0;

    async function worker(workerId) {
        while (true) {
            const index =
                nextIndex++;

            if (
                index >= cleanProducts.length
            ) {
                break;
            }

            const product =
                cleanProducts[index];

            if (!product.product_id) {
                completed++;

                updateProgress({
                    stage: "Collecting Variants",
                    current: completed,
                    total: cleanProducts.length
                });

                continue;
            }

            try {
                const result =
                    await fetchVariants(
                        product.product_id,
                        product.price
                    );

                product.variants =
                    result.variants;

                product.offers =
                    result.offers;

                product.max_quantity_allowed =
                    result.max_quantity_allowed;

                product.seller_available_stock =
                    result.seller_available_stock;

                if (result.stock !== null) {
                    product.stock = result.stock;
                }

                totalVariants +=
                    product.variants.length;
            }
            catch (error) {
                failedVariants++;

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
                `[tata](collecting data) [Worker ${workerId}] ` +
                `${completed}/${cleanProducts.length}` +
                ` | Product ${product.product_id}` +
                ` | Variants: ${product.variants.length}` +
                ` | Offers: ${product.offers.length}` +
                ` | Stock: ${product.seller_available_stock ?? product.stock}`
            );

            await sleep(
                1000 + Math.random() * 1000
            );
        }
    }

    console.log(
        `Fetching details/offers using ${CONCURRENCY} workers...`
    );

    updateProgress({
        stage: "Collecting Variants",
        current: 0,
        total: cleanProducts.length
    });

    await Promise.all(
        Array.from(
            { length: CONCURRENCY },
            (_, index) =>
                worker(index + 1)
        )
    );

    const output = {
        schema_version: 2,

        source: "tatacliq",

        scrape_date:
            new Date()
                .toISOString()
                .slice(0, 10),

        scraped_at:
            new Date()
                .toISOString(),

        expected_products:
            totalResults,

        total_products:
            cleanProducts.length,

        total_variants:
            totalVariants,

        average_variants_per_product:
            Number(
                (
                    totalVariants /
                    Math.max(
                        cleanProducts.length,
                        1
                    )
                ).toFixed(2)
            ),

        failed_detail_requests:
            failedVariants,

        products:
            cleanProducts
    };

    if (typeof window !== "undefined") {
        window.__FINAL_RESULT__ = output;
        window.__SCRAPER_DONE__ = true;
    }

    if (typeof document !== "undefined" && document.createElement) {
        try {
            const blob =
                new Blob(
                    [
                        JSON.stringify(
                            output,
                            null,
                            2
                        )
                    ],
                    {
                        type: "application/json"
                    }
                );

            const downloadUrl =
                URL.createObjectURL(blob);

            const link =
                document.createElement("a");

            link.href = downloadUrl;
            link.download =
                "tatacliq_columbia_products_with_offers.json";

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

    console.log("SCRAPE COMPLETE:", output.total_products, "products,", output.total_variants, "variants.");
    return output;
})();
