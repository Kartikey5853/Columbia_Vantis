(async () => {

    // ============================================================
    // TATA CLIQ LUXURY - COLUMBIA SCRAPER
    //
    // Portable:
    //   - No cookies
    //   - No x-client-id
    //   - No x-cli-ubid
    //   - No MCVID
    //   - No session-specific values
    //
    // Pipeline:
    //   Lux Listing API
    //        ↓
    //   Product IDs / metadata
    //        ↓
    //   PDP HTML
    //        ↓
    //   Product JSON / Price / variantOptions / sizeOptions
    //        ↓
    //   Final JSON
    //
    // PRICE FIX:
    //   Listing API price
    //        ↓
    //   PDP embedded product JSON
    //        ↓
    //   JSON-LD
    //        ↓
    //   HTML price fallback
    // ============================================================


    // ============================================================
    // CONFIG
    // ============================================================

    const SEARCH_TEXT =
        "Columbia:relevance:list:listId_3b2c31cb7dc142898a1f01694ec87d79";


    const PAGE_SIZE = 24;


    const LISTING_RETRIES = 3;

    const PDP_RETRIES = 3;


    const CONCURRENCY = 5;


    const LISTING_DELAY_MIN = 1200;

    const LISTING_DELAY_MAX = 2500;


    const PDP_DELAY_MIN = 800;

    const PDP_DELAY_MAX = 1800;


    const PDP_RETRY_DELAY = 4000;



    // ============================================================
    // ENDPOINTS
    // ============================================================

    const LISTING_BASE =
        "https://cliqapi.tatacliq.com/cliq-api/v1/lux/search";


    const PDP_BASE =
        "https://luxury.tatacliq.com";



    // ============================================================
    // HELPERS
    // ============================================================

    const sleep = ms =>
        new Promise(
            resolve =>
                setTimeout(
                    resolve,
                    ms
                )
        );


    const randomDelay = (
        min,
        max
    ) =>
        min +
        Math.floor(
            Math.random() *
            (max - min + 1)
        );



    // ============================================================
    // ABSOLUTE URL
    // ============================================================

    const absoluteUrl = value => {

        if (!value) {
            return "";
        }


        if (
            value.startsWith("http://")
        ) {
            return value;
        }


        if (
            value.startsWith("https://")
        ) {
            return value;
        }


        if (
            value.startsWith("//")
        ) {
            return "https:" + value;
        }


        if (
            value.startsWith("/")
        ) {
            return PDP_BASE + value;
        }


        return PDP_BASE + "/" + value;
    };



    // ============================================================
    // SAFE NUMBER
    // ============================================================

    const safeNumber = value => {

        if (
            value === null ||
            value === undefined ||
            value === ""
        ) {
            return 0;
        }


        if (
            typeof value === "number"
        ) {

            return Number.isFinite(value)
                ? value
                : 0;
        }


        const cleaned =
            String(value)
                .replace(
                    /[^0-9.-]/g,
                    ""
                );


        const number =
            Number(cleaned);


        return Number.isFinite(number)
            ? number
            : 0;
    };



    // ============================================================
    // PROGRESS
    // ============================================================

    const progressStartedAt =
        Date.now();


    window.updateProgress =
        function (progress) {

            const current =
                Number(
                    progress.current || 0
                );


            const total =
                Number(
                    progress.total || 0
                );


            const elapsedSeconds =
                Math.max(
                    0,
                    (
                        Date.now() -
                        progressStartedAt
                    ) / 1000
                );


            const etaSeconds =
                current > 0 &&
                total > current
                    ? Math.round(
                        (
                            elapsedSeconds /
                            current
                        ) *
                        (
                            total -
                            current
                        )
                    )
                    : 0;


            const payload = {

                ...progress,


                current,


                total,


                elapsed_seconds:
                    Math.round(
                        elapsedSeconds
                    ),


                eta_seconds:
                    etaSeconds,


                updated_at:
                    new Date()
                        .toISOString()
            };


            window.__SCRAPER_PROGRESS__ =
                payload;


            if (
                typeof window.updateScraperProgress ===
                "function"
            ) {

                try {

                    const res =
                        window.updateScraperProgress(
                            payload
                        );


                    if (
                        res &&
                        typeof res.catch ===
                        "function"
                    ) {

                        res.catch(
                            () => {}
                        );
                    }

                }
                catch (_) {}
            }
        };



    // ============================================================
    // BUILD LISTING URL
    // ============================================================

    function buildListingUrl(page) {

        const params =
            new URLSearchParams({

                pageSize:
                    String(
                        PAGE_SIZE
                    ),


                isTextSearch:
                    "false",


                isFilter:
                    "false",


                isPwa:
                    "true",


                channel:
                    "web",


                typeID:
                    "all",


                page:
                    String(page),


                searchText:
                    SEARCH_TEXT,


                isSortFlow:
                    "false",


                isSuggested:
                    "false",


                isMDE:
                    "true",


                test:
                    "es.template.binning.qpsv4",


                qc:
                    "false",


                isKeywordRedirect:
                    "false",


                isKeywordRedirectEnabled:
                    "false",


                isFilterDataRequired:
                    "false",


                ad:
                    "true"

            });


        return (
            `${LISTING_BASE}?${params}`
        );
    }



    // ============================================================
    // FETCH LISTING PAGE
    // ============================================================

    async function fetchListingPage(page) {

        const url =
            buildListingUrl(
                page
            );


        const response =
            await fetch(
                url,
                {

                    method:
                        "GET",


                    credentials:
                        "omit",


                    headers: {

                        "appplatform":
                            "web",


                        "appversion":
                            "v1",


                        "x-provider-id":
                            "cliq-search",


                        "Accept":
                            "application/json"

                    }

                }
            );


        if (
            !response.ok
        ) {

            throw new Error(
                `Listing HTTP ${response.status}`
            );
        }


        const data =
            await response.json();


        if (
            data?.status &&
            String(
                data.status
            ).toLowerCase() !==
            "success"
        ) {

            throw new Error(
                `Listing API status: ${data.status}`
            );
        }


        if (
            !Array.isArray(
                data.searchresult
            )
        ) {

            throw new Error(
                "Listing response contains no searchresult array"
            );
        }


        return data;
    }



    // ============================================================
    // FETCH LISTING PAGE WITH RETRIES
    // ============================================================

    async function fetchListingWithRetry(
        page
    ) {

        let lastError =
            null;


        for (
            let attempt = 1;
            attempt <= LISTING_RETRIES;
            attempt++
        ) {

            try {

                console.log(
                    `Listing page ${page + 1} | Attempt ${attempt}`
                );


                const data =
                    await fetchListingPage(
                        page
                    );


                return data;

            }


            catch (error) {

                lastError =
                    error;


                console.warn(
                    `Listing page ${page + 1} failed:`,
                    error.message
                );


                if (
                    attempt <
                    LISTING_RETRIES
                ) {

                    await sleep(
                        PDP_RETRY_DELAY
                    );
                }
            }
        }


        throw (
            lastError ||
            new Error(
                `Listing page ${page + 1} failed`
            )
        );
    }



    // ============================================================
    // NORMALIZE LISTING PRODUCT
    // ============================================================

    function normalizeProduct(p) {

        return {

            source:
                "tata_lux",


            product_id:
                String(
                    p?.productId ||
                    ""
                ),


            sku:
                "",


            ean:
                "",


            available:
                !!p?.inStockFlag,


            title:
                p?.productname ||
                "",


            brand:
                p?.brandname ||
                "",


            price:
                safeNumber(
                    p?.price?.sellingPrice
                ),


            mrp:
                safeNumber(
                    p?.price?.mrpPrice
                ) ||
                safeNumber(
                    p?.price?.sellingPrice
                ),


            // This tells us whether the initial
            // listing API supplied a price.
            price_source:
                safeNumber(
                    p?.price?.sellingPrice
                ) > 0
                    ? "listing"
                    : "unavailable",


            image_url:
                absoluteUrl(
                    p?.imageURL ||
                    ""
                ),


            url:
                absoluteUrl(
                    p?.webURL ||
                    ""
                ),


            variants:
                [],


            scraped_at:
                new Date()
                    .toISOString()

        };
    }



    // ============================================================
    // PDP URL
    // ============================================================

    function buildPdpUrl(
        product
    ) {

        if (
            product?.url
        ) {

            return product.url;
        }


        if (
            product?.product_id
        ) {

            return (
                `${PDP_BASE}/p-` +
                product.product_id
                    .toLowerCase()
            );
        }


        return "";
    }



    // ============================================================
    // FETCH PDP HTML
    // ============================================================

    async function fetchPdpHtml(
        product
    ) {

        const url =
            buildPdpUrl(
                product
            );


        if (!url) {

            throw new Error(
                "No PDP URL"
            );
        }


        const response =
            await fetch(
                url,
                {

                    method:
                        "GET",


                    credentials:
                        "omit",


                    headers: {

                        "Accept":
                            "text/html,application/xhtml+xml"

                    }

                }
            );


        if (
            !response.ok
        ) {

            throw new Error(
                `PDP HTTP ${response.status}`
            );
        }


        const html =
            await response.text();


        if (
            !html ||
            html.length < 1000
        ) {

            throw new Error(
                `PDP HTML too small: ${html.length}`
            );
        }


        return html;
    }



    // ============================================================
    // EXTRACT JSON OBJECT FROM HTML
    //
    // Tata Lux embeds the product object directly into
    // the PDP HTML.
    //
    // We locate "variantOptions" and walk backwards/
    // forwards through the JSON text.
    // ============================================================

    function extractJsonContainingVariantOptions(
        html
    ) {

        const key =
            '"variantOptions"';


        const variantIndex =
            html.indexOf(
                key
            );


        if (
            variantIndex === -1
        ) {

            return null;
        }


        const MAX_BACKTRACK =
            200000;


        const startLimit =
            Math.max(
                0,
                variantIndex -
                MAX_BACKTRACK
            );


        let depth = 0;

        let objectStart = -1;


        for (
            let i = variantIndex;
            i >= startLimit;
            i--
        ) {

            const char =
                html[i];


            if (
                char === "}"
            ) {

                depth++;

                continue;
            }


            if (
                char === "{"
            ) {

                if (
                    depth > 0
                ) {

                    depth--;

                    continue;
                }


                objectStart =
                    i;

                break;
            }
        }


        const candidateStarts =
            [];


        if (
            objectStart !== -1
        ) {

            candidateStarts.push(
                objectStart
            );
        }


        for (
            let i =
                variantIndex - 1;

            i >= startLimit &&
            candidateStarts.length < 100;

            i--
        ) {

            if (
                html[i] === "{"
            ) {

                candidateStarts.push(
                    i
                );
            }
        }


        for (
            const start
            of candidateStarts
        ) {

            let depthCount = 0;

            let stringMode = false;

            let escapeMode = false;


            for (
                let i = start;
                i < html.length;
                i++
            ) {

                const char =
                    html[i];


                if (
                    stringMode
                ) {

                    if (
                        escapeMode
                    ) {

                        escapeMode =
                            false;

                        continue;
                    }


                    if (
                        char === "\\"
                    ) {

                        escapeMode =
                            true;

                        continue;
                    }


                    if (
                        char === '"'
                    ) {

                        stringMode =
                            false;
                    }


                    continue;
                }


                if (
                    char === '"'
                ) {

                    stringMode =
                        true;

                    continue;
                }


                if (
                    char === "{"
                ) {

                    depthCount++;
                }


                else if (
                    char === "}"
                ) {

                    depthCount--;


                    if (
                        depthCount === 0
                    ) {

                        const candidate =
                            html.slice(
                                start,
                                i + 1
                            );


                        if (
                            candidate.includes(
                                '"variantOptions"'
                            )
                        ) {

                            try {

                                const parsed =
                                    JSON.parse(
                                        candidate
                                    );


                                if (
                                    parsed?.variantOptions ||
                                    parsed?.variantGroup
                                ) {

                                    return parsed;
                                }

                            }
                            catch (_) {

                                // Keep trying.
                            }
                        }


                        break;
                    }
                }
            }
        }


        return null;
    }



    // ============================================================
    // GENERIC FALLBACK:
    // FIND VARIANT ARRAYS DIRECTLY
    // ============================================================

    function extractVariantOptionsFallback(
        html
    ) {

        const marker =
            '"variantOptions":[';


        const index =
            html.indexOf(
                marker
            );


        if (
            index === -1
        ) {

            return [];
        }


        const arrayStart =
            index +
            '"variantOptions":'.length;


        let depth = 0;

        let inString = false;

        let escaped = false;


        for (
            let i = arrayStart;
            i < html.length;
            i++
        ) {

            const char =
                html[i];


            if (
                inString
            ) {

                if (
                    escaped
                ) {

                    escaped =
                        false;

                }


                else if (
                    char === "\\"
                ) {

                    escaped =
                        true;

                }


                else if (
                    char === '"'
                ) {

                    inString =
                        false;
                }


                continue;
            }


            if (
                char === '"'
            ) {

                inString =
                    true;

                continue;
            }


            if (
                char === "["
            ) {

                depth++;

            }


            else if (
                char === "]"
            ) {

                depth--;


                if (
                    depth === 0
                ) {

                    const raw =
                        html.slice(
                            arrayStart,
                            i + 1
                        );


                    try {

                        return JSON.parse(
                            raw
                        );

                    }
                    catch (_) {

                        return [];
                    }
                }
            }
        }


        return [];
    }

        // ============================================================
    // PRICE EXTRACTION
    //
    // Tata CLiQ Luxury may expose price in the PDP HTML/app state
    // instead of the listing API.
    //
    // Priority:
    //
    //   1. Embedded product JSON
    //   2. JSON-LD
    //   3. Direct HTML price fields
    // ============================================================


    function firstPositiveNumber(
        ...values
    ) {

        for (
            const value
            of values
        ) {

            const n =
                safeNumber(
                    value
                );


            if (
                n > 0
            ) {

                return n;
            }
        }


        return 0;
    }



    // ============================================================
    // EXTRACT PRICE FROM OBJECT
    // ============================================================

    function extractPriceFromObject(
        root
    ) {

        if (
            !root ||
            typeof root !== "object"
        ) {

            return {

                price: 0,

                mrp: 0

            };
        }


        let price = 0;

        let mrp = 0;


        const visited =
            new Set();



        // --------------------------------------------------------
        // POSSIBLE SELLING PRICE KEYS
        // --------------------------------------------------------

        const priceKeys = [

            "sellingPrice",

            "salePrice",

            "discountedPrice",

            "offerPrice",

            "finalPrice",

            "currentPrice",

            "selling_price",

            "sale_price",

            "discounted_price",

            "offer_price",

            "final_price",

            "current_price"

        ];



        // --------------------------------------------------------
        // POSSIBLE MRP KEYS
        // --------------------------------------------------------

        const mrpKeys = [

            "mrpPrice",

            "mrp",

            "listPrice",

            "originalPrice",

            "maximumRetailPrice",

            "mrp_price",

            "list_price",

            "original_price"

        ];



        // --------------------------------------------------------
        // RECURSIVE WALK
        // --------------------------------------------------------

        function walk(
            node
        ) {

            if (
                !node ||
                typeof node !== "object" ||
                visited.has(node)
            ) {

                return;
            }


            visited.add(
                node
            );



            // ----------------------------------------------------
            // ARRAY
            // ----------------------------------------------------

            if (
                Array.isArray(node)
            ) {

                for (
                    const item
                    of node
                ) {

                    walk(
                        item
                    );
                }


                return;
            }



            // ----------------------------------------------------
            // SELLING PRICE
            // ----------------------------------------------------

            for (
                const key
                of priceKeys
            ) {

                if (
                    price === 0 &&
                    Object.prototype.hasOwnProperty.call(
                        node,
                        key
                    )
                ) {

                    price =
                        firstPositiveNumber(
                            node[key]
                        );
                }
            }



            // ----------------------------------------------------
            // MRP
            // ----------------------------------------------------

            for (
                const key
                of mrpKeys
            ) {

                if (
                    mrp === 0 &&
                    Object.prototype.hasOwnProperty.call(
                        node,
                        key
                    )
                ) {

                    mrp =
                        firstPositiveNumber(
                            node[key]
                        );
                }
            }



            // ----------------------------------------------------
            // NESTED PRICE OBJECT
            //
            // Example:
            //
            // price: {
            //     sellingPrice: 4999,
            //     mrpPrice: 6999
            // }
            // ----------------------------------------------------

            const nestedPrice =
                node.price;


            if (
                nestedPrice &&
                typeof nestedPrice ===
                "object"
            ) {

                if (
                    price === 0
                ) {

                    price =
                        firstPositiveNumber(

                            nestedPrice.sellingPrice,

                            nestedPrice.salePrice,

                            nestedPrice.discountedPrice,

                            nestedPrice.offerPrice,

                            nestedPrice.finalPrice,

                            nestedPrice.currentPrice,

                            nestedPrice.value
                        );
                }


                if (
                    mrp === 0
                ) {

                    mrp =
                        firstPositiveNumber(

                            nestedPrice.mrpPrice,

                            nestedPrice.mrp,

                            nestedPrice.listPrice,

                            nestedPrice.originalPrice,

                            nestedPrice.maximumRetailPrice
                        );
                }
            }



            // ----------------------------------------------------
            // RECURSE THROUGH ALL OBJECTS
            // ----------------------------------------------------

            for (
                const [key, value]
                of Object.entries(node)
            ) {

                if (
                    key === "price"
                ) {

                    continue;
                }


                if (
                    value &&
                    typeof value ===
                    "object"
                ) {

                    walk(
                        value
                    );
                }
            }
        }



        walk(
            root
        );



        // --------------------------------------------------------
        // FALLBACKS
        // --------------------------------------------------------

        if (
            price === 0 &&
            mrp > 0
        ) {

            price =
                mrp;
        }


        if (
            mrp === 0 &&
            price > 0
        ) {

            mrp =
                price;
        }



        return {

            price,

            mrp

        };
    }



    // ============================================================
    // EXTRACT PRICE FROM PDP HTML
    // ============================================================

    function extractPriceFromHtml(
        html,
        productObject
    ) {


        // ========================================================
        // METHOD 1
        // EMBEDDED PRODUCT OBJECT
        // ========================================================

        const fromObject =
            extractPriceFromObject(
                productObject
            );


        if (
            fromObject.price > 0
        ) {

            console.log(
                "[PRICE] Found in embedded PDP object:",
                fromObject
            );


            return fromObject;
        }



        // ========================================================
        // METHOD 2
        // JSON-LD
        // ========================================================

        try {

            const blocks =
                html.match(
                    /<script[^>]+type=["']application\/ld\+json["'][^>]*>[\s\S]*?<\/script>/gi
                ) || [];


            for (
                const block
                of blocks
            ) {

                const raw =
                    block
                        .replace(
                            /^.*?>/,
                            ""
                        )
                        .replace(
                            /<\/script>\s*$/i,
                            ""
                        )
                        .trim();


                try {

                    const parsed =
                        JSON.parse(
                            raw
                        );


                    const nodes =
                        Array.isArray(
                            parsed
                        )
                            ? parsed
                            : [parsed];


                    for (
                        const node
                        of nodes
                    ) {

                        if (
                            !node
                        ) {

                            continue;
                        }


                        const offers =
                            Array.isArray(
                                node?.offers
                            )
                                ? node.offers
                                : [
                                    node?.offers
                                ];


                        for (
                            const offer
                            of offers
                        ) {

                            if (
                                !offer
                            ) {

                                continue;
                            }


                            const offerPrice =
                                firstPositiveNumber(

                                    offer.price,

                                    offer.lowPrice
                                );


                            if (
                                offerPrice > 0
                            ) {

                                const result = {

                                    price:
                                        offerPrice,


                                    mrp:
                                        firstPositiveNumber(

                                            offer.highPrice,

                                            offer.price
                                        )

                                };


                                console.log(
                                    "[PRICE] Found in JSON-LD:",
                                    result
                                );


                                return result;
                            }
                        }
                    }

                }
                catch (_) {

                    // Ignore malformed JSON-LD.
                }
            }

        }
        catch (_) {

            // Ignore JSON-LD extraction errors.
        }



        // ========================================================
        // METHOD 3
        // DIRECT HTML FALLBACK
        // ========================================================

        let price = 0;

        let mrp = 0;



        // --------------------------------------------------------
        // SELLING PRICE
        // --------------------------------------------------------

        const priceMatch =
            html.match(

                /"(?:sellingPrice|salePrice|discountedPrice|offerPrice|finalPrice|currentPrice)"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)"?/i

            );



        // --------------------------------------------------------
        // MRP
        // --------------------------------------------------------

        const mrpMatch =
            html.match(

                /"(?:mrpPrice|mrp|listPrice|originalPrice)"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)"?/i

            );



        if (
            priceMatch
        ) {

            price =
                safeNumber(
                    priceMatch[1]
                );
        }


        if (
            mrpMatch
        ) {

            mrp =
                safeNumber(
                    mrpMatch[1]
                );
        }



        // --------------------------------------------------------
        // FINAL FALLBACKS
        // --------------------------------------------------------

        if (
            price === 0 &&
            mrp > 0
        ) {

            price =
                mrp;
        }


        if (
            mrp === 0 &&
            price > 0
        ) {

            mrp =
                price;
        }



        const result = {

            price,

            mrp

        };


        console.log(
            "[PRICE] HTML fallback:",
            result
        );


        return result;
    }



    // ============================================================
    // PARSE VARIANTS
    // ============================================================

    function parseVariants(
        html
    ) {

        /*
         * Preferred:
         * Parse the complete embedded product JSON.
         */

        const productObject =
            extractJsonContainingVariantOptions(
                html
            );


        let rawVariants =
            [];


        if (
            Array.isArray(
                productObject?.variantOptions
            )
        ) {

            rawVariants =
                productObject.variantOptions;
        }



        /*
         * Fallback:
         * Directly extract variantOptions array.
         */

        if (
            rawVariants.length === 0
        ) {

            rawVariants =
                extractVariantOptionsFallback(
                    html
                );
        }



        /*
         * If variantOptions isn't available,
         * use variantGroup.
         */

        if (
            rawVariants.length === 0 &&
            Array.isArray(
                productObject?.variantGroup
            )
        ) {

            const flattened =
                [];


            for (
                const group
                of productObject.variantGroup
            ) {

                const sizes =
                    Array.isArray(
                        group?.sizeOptions
                    )
                        ? group.sizeOptions
                        : [];


                for (
                    const size
                    of sizes
                ) {

                    flattened.push({

                        colorlink:
                            group.colorLink ||
                            {},


                        sizelink:
                            size

                    });
                }
            }


            rawVariants =
                flattened;
        }



        /*
         * Normalize variants.
         */

        const variants =
            [];


        for (
            const variant
            of rawVariants
        ) {

            const sizeLink =
                variant?.sizelink ||
                variant?.sizeLink ||
                variant ||
                {};


            const colorLink =
                variant?.colorlink ||
                variant?.colorLink ||
                {};


            const sku =
                String(
                    sizeLink?.productCode ||
                    ""
                );


            const size =
                sizeLink?.size ||
                sizeLink?.brandSize ||
                "";


            const url =
                absoluteUrl(
                    sizeLink?.url ||
                    colorLink?.colorurl ||
                    ""
                );


            /*
             * Avoid completely empty garbage entries.
             */

            if (
                !sku &&
                !size &&
                !url
            ) {

                continue;
            }


            variants.push({

                size:
                    String(
                        size
                    ),


                sku:
                    sku,


                available:
                    !!sizeLink?.isAvailable,


                stock:
                    safeNumber(
                        sizeLink?.stockCount
                    ),


                url:
                    url

            });
        }



        /*
         * Deduplicate variants by SKU first,
         * then URL/size.
         */

        const seen =
            new Set();


        return variants.filter(
            variant => {

                const key =
                    variant.sku ||
                    `${variant.size}|${variant.url}`;


                if (
                    seen.has(key)
                ) {

                    return false;
                }


                seen.add(
                    key
                );


                return true;

            }
        );
    }

        // ============================================================
    // FETCH + PARSE ONE PDP
    // ============================================================

    async function scrapePdp(
        product
    ) {

        let lastError =
            null;


        for (
            let attempt = 1;
            attempt <= PDP_RETRIES;
            attempt++
        ) {

            try {

                // ------------------------------------------------
                // FETCH PDP
                // ------------------------------------------------

                const html =
                    await fetchPdpHtml(
                        product
                    );



                // ------------------------------------------------
                // EXTRACT EMBEDDED PRODUCT OBJECT
                //
                // This same object is used for:
                //
                //   - variants
                //   - price
                //   - MRP
                // ------------------------------------------------

                const productObject =
                    extractJsonContainingVariantOptions(
                        html
                    );



                // ------------------------------------------------
                // PARSE VARIANTS
                // ------------------------------------------------

                const variants =
                    parseVariants(
                        html
                    );



                // ------------------------------------------------
                // VARIANT VALIDATION
                // ------------------------------------------------

                if (
                    variants.length === 0
                ) {

                    /*
                     * Don't immediately call this a hard failure.
                     *
                     * Some products genuinely have no size variants.
                     */

                    const hasVariantMarkers =
                        html.includes(
                            '"variantOptions"'
                        ) ||
                        html.includes(
                            '"variantGroup"'
                        ) ||
                        html.includes(
                            '"sizeOptions"'
                        );


                    if (
                        hasVariantMarkers
                    ) {

                        throw new Error(
                            "Variant data found but could not be parsed"
                        );
                    }
                }



                // ------------------------------------------------
                // PRICE EXTRACTION
                // ------------------------------------------------

                const priceData =
                    extractPriceFromHtml(
                        html,
                        productObject
                    );


                console.log(
                    `[PRICE] ${product.product_id} | ` +
                    `Price: ${priceData.price} | ` +
                    `MRP: ${priceData.mrp}`
                );



                // ------------------------------------------------
                // RETURN PDP DATA
                // ------------------------------------------------

                return {

                    variants,


                    price:
                        priceData.price,


                    mrp:
                        priceData.mrp,


                    htmlLength:
                        html.length

                };

            }


            catch (error) {

                lastError =
                    error;


                console.warn(
                    `PDP failed ${product.product_id} | Attempt ${attempt}:`,
                    error.message
                );


                if (
                    attempt <
                    PDP_RETRIES
                ) {

                    await sleep(
                        PDP_RETRY_DELAY
                    );
                }
            }
        }


        throw (
            lastError ||
            new Error(
                "PDP scraping failed"
            )
        );
    }



    // ============================================================
    // STORAGE & LISTING CHECKPOINTS
    // ============================================================

    const products = [];
    const productIds = new Set();
    let listingFailedPages = [];
    let failedPdpProducts = [];
    let totalVariants = 0;

    window.__TATA_LUX_UNSAVED_LISTINGS__ = window.__TATA_LUX_UNSAVED_LISTINGS__ || [];
    window.drainUnsavedListings = function () {
        const u = window.__TATA_LUX_UNSAVED_LISTINGS__ || [];
        window.__TATA_LUX_UNSAVED_LISTINGS__ = [];
        return u;
    };

    // ============================================================
    // START
    // ============================================================

    console.clear();
    console.log("");
    console.log("==============================================");
    console.log(" TATA CLIQ LUXURY - COLUMBIA SCRAPER");
    console.log("==============================================");
    console.log("");
    console.log("Listing API : Lux Search");
    console.log("PDP source  : PDP HTML");
    console.log("Price       : PDP + JSON-LD + HTML fallback");
    console.log("Concurrency : " + CONCURRENCY);
    console.log("");
    console.log("Starting...");
    console.log("");

    // ============================================================
    // ADD LISTING PRODUCTS
    // ============================================================

    function addListingProducts(items, pageNumber = 0) {
        if (!Array.isArray(items)) return [];
        const newItemsThisPage = [];
        for (const rawProduct of items) {
            const product = normalizeProduct(rawProduct);
            if (!product.product_id) continue;
            if (productIds.has(product.product_id)) continue;
            productIds.add(product.product_id);
            products.push(product);
            newItemsThisPage.push(product);
        }
        if (newItemsThisPage.length > 0) {
            window.__TATA_LUX_UNSAVED_LISTINGS__.push({
                page: pageNumber,
                products: newItemsThisPage
            });
            window.__TATA_LUX_LAST_LISTING_PAGE__ = pageNumber;
        }
        return newItemsThisPage;
    }

    // ============================================================
    // LISTING PAGES PAGINATION (PHASE 1)
    // ============================================================

    const startPage = typeof window.__START_PAGE__ !== "undefined" ? Number(window.__START_PAGE__) : 0;
    let totalPages = 1;
    let totalResults = 0;

    if (startPage === 0) {
        let first;
        try {
            first = await fetchListingWithRetry(0);
        } catch (error) {
            console.error("FATAL: Could not fetch first listing page.", error);
            window.__SCRAPER_DONE__ = true;
            return;
        }

        const pagination = first.pagination || {};
        totalPages = Number(pagination.totalPages || 0);
        totalResults = Number(pagination.totalResults || 0);
        console.log(`Found ${totalResults} products across ${totalPages} pages`);

        if (totalPages <= 0) {
            console.error("FATAL: API returned no pages.");
            window.__SCRAPER_DONE__ = true;
            return;
        }

        addListingProducts(first.searchresult, 0);
        updateProgress({
            stage: "Collecting Products",
            current: 1,
            total: totalPages,
            products: products.length
        });
        console.log(`Page 1/${totalPages} | Products: ${products.length}`);
    } else {
        try {
            const probe = await fetchListingWithRetry(0);
            totalPages = Number(probe.pagination?.totalPages || 1);
            totalResults = Number(probe.pagination?.totalResults || 0);
        } catch (_) {
            totalPages = startPage + 20;
        }
    }

    const loopStart = Math.max(1, startPage);
    for (let page = loopStart; page < totalPages; page++) {
        if (typeof window.__PRODUCT_LIMIT__ !== "undefined" && window.__PRODUCT_LIMIT__ > 0 && products.length >= window.__PRODUCT_LIMIT__) {
            console.log(`[TEST MODE] Reached product limit ${window.__PRODUCT_LIMIT__}, stopping listing pagination.`);
            break;
        }

        try {
            const data = await fetchListingWithRetry(page);
            addListingProducts(data.searchresult, page);
            console.log(`Page ${page + 1}/${totalPages} | Products: ${products.length}`);
            updateProgress({
                stage: "Collecting Products",
                current: page + 1,
                total: totalPages,
                products: products.length
            });
        } catch (error) {
            console.error(`SKIPPED LISTING PAGE ${page + 1}:`, error.message);
            listingFailedPages.push(page);
        }

        await sleep(randomDelay(LISTING_DELAY_MIN, LISTING_DELAY_MAX));
    }

    // ============================================================
    // LISTING COMPLETE
    // ============================================================

    console.log("");
    console.log("----------------------------------------------");
    console.log("LISTING COLLECTION COMPLETE");
    console.log("----------------------------------------------");
    console.log(`Expected products : ${totalResults}`);
    console.log(`Collected products: ${products.length}`);
    console.log(`Missing products  : ${Math.max(0, totalResults - products.length)}`);
    console.log(`Failed pages      : ${listingFailedPages.length}`);
    console.log("----------------------------------------------");
    console.log("");

    if (typeof window.__PRODUCT_LIMIT__ !== "undefined" && window.__PRODUCT_LIMIT__ > 0) {
        products.length = Math.min(products.length, window.__PRODUCT_LIMIT__);
        console.log(`[TEST MODE] Truncated product list to ${products.length} items`);
    }

    // If running in listings_only phase, exit cleanly after completing Phase 1
    if (window.__PHASE__ === "listings_only") {
        console.log(`[TATA LUX LISTINGS] Phase 1 listings complete (${products.length} products). Stopping before Phase 2.`);
        updateProgress({ stage: "Listings Complete", current: products.length, total: products.length });
        window.__LISTINGS_DONE__ = true;
        window.__SCRAPER_DONE__ = true;
        return;
    }


    console.log(
        "----------------------------------------------"
    );


    console.log(
        `Expected products : ${totalResults}`
    );


    console.log(
        `Collected products: ${products.length}`
    );


    console.log(
        `Missing products  : ${
            Math.max(
                0,
                totalResults -
                products.length
            )
        }`
    );


    console.log(
        `Failed pages      : ${listingFailedPages.length}`
    );


    console.log(
        "----------------------------------------------"
    );


    console.log("");



    if (
        listingFailedPages.length
    ) {

        console.warn(
            "Failed listing pages:",
            listingFailedPages.map(
                p =>
                    p + 1
            )
        );
    }

        // ============================================================
    // PDP WORKERS
    // ============================================================

    let nextIndex =
        0;


    let completed =
        0;



    // ============================================================
    // WORKER
    // ============================================================

    async function worker(
        workerId
    ) {

        while (true) {

            const index =
                nextIndex++;


            if (
                index >= products.length
            ) {

                break;
            }


            const product =
                products[index];


            try {

                // ------------------------------------------------
                // SCRAPE PDP
                // ------------------------------------------------

                const result =
                    await scrapePdp(
                        product
                    );



                // ------------------------------------------------
                // VARIANTS
                // ------------------------------------------------

                product.variants =
                    result.variants;



                // ------------------------------------------------
                // PRICE
                //
                // IMPORTANT:
                //
                // PDP price takes priority.
                //
                // If PDP price is unavailable,
                // the original listing API price
                // is preserved.
                // ------------------------------------------------

                if (
                    result.price > 0
                ) {

                    product.price =
                        result.price;
                }



                // ------------------------------------------------
                // MRP
                // ------------------------------------------------

                if (
                    result.mrp > 0
                ) {

                    product.mrp =
                        result.mrp;
                }



                // ------------------------------------------------
                // PRICE SOURCE
                // ------------------------------------------------

                product.price_source =
                    result.price > 0
                        ? "pdp"
                        : (
                            product.price > 0
                                ? "listing"
                                : "unavailable"
                        );



                // ------------------------------------------------
                // PDP HTML SIZE
                // ------------------------------------------------

                product.pdp_html_length =
                    result.htmlLength;

            }


            catch (error) {

                // ------------------------------------------------
                // PDP FAILED
                // ------------------------------------------------

                product.variants =
                    [];


                product.variant_error =
                    error.message;


                /*
                 * IMPORTANT:
                 *
                 * We do NOT delete the listing price.
                 *
                 * If the listing API had a price,
                 * it remains available.
                 */

                if (
                    product.price > 0
                ) {

                    product.price_source =
                        "listing";

                }
                else {

                    product.price_source =
                        "unavailable";
                }


                failedPdpProducts.push(
                    product.product_id
                );
            }



            // ----------------------------------------------------
            // PROGRESS
            // ----------------------------------------------------

            completed++;


            totalVariants +=
                product.variants.length;


            const average =
                totalVariants /
                Math.max(
                    completed,
                    1
                );



            updateProgress({

                stage:
                    "Collecting Variants",


                current:
                    completed,


                total:
                    products.length,


                total_variants:
                    totalVariants,


                failed_products:
                    failedPdpProducts.length

            });



            // ----------------------------------------------------
            // LOG
            // ----------------------------------------------------

            console.log(

                `[Worker ${workerId}] ` +

                `${completed}/${products.length}` +

                ` | ${product.product_id}` +

                ` | Price: ${product.price || 0}` +

                ` | MRP: ${product.mrp || 0}` +

                ` | Source: ${product.price_source}` +

                ` | Variants: ${product.variants.length}` +

                ` | Total: ${totalVariants}` +

                ` | Avg: ${average.toFixed(2)}` +

                ` | Failed: ${failedPdpProducts.length}`

            );



            // ----------------------------------------------------
            // CHECKPOINT
            // ----------------------------------------------------

            if (
                completed % 100 === 0 ||
                completed === products.length
            ) {

                console.log("");


                console.log(
                    "----------------------------------------------"
                );


                console.log(
                    `CHECKPOINT ${completed}/${products.length}`
                );


                console.log(
                    `Variants : ${totalVariants}`
                );


                console.log(
                    `Average  : ${average.toFixed(2)}`
                );


                console.log(
                    `Failed   : ${failedPdpProducts.length}`
                );


                console.log(
                    "----------------------------------------------"
                );


                console.log("");
            }



            // ----------------------------------------------------
            // DELAY BETWEEN PDP REQUESTS
            // ----------------------------------------------------

            await sleep(
                randomDelay(
                    PDP_DELAY_MIN,
                    PDP_DELAY_MAX
                )
            );
        }
    }



    // ============================================================
    // START PDP STAGE
    // ============================================================

    console.log("");


    console.log(
        "=============================================="
    );


    console.log(
        `FETCHING PDPs USING ${CONCURRENCY} WORKERS`
    );


    console.log(
        "=============================================="
    );


    console.log("");



    updateProgress({

        stage:
            "Collecting Variants",


        current:
            0,


        total:
            products.length,


        total_variants:
            0,


        failed_products:
            0

    });



    // ============================================================
    // START WORKERS
    // ============================================================

    await Promise.all(

        Array.from(
            {

                length:
                    CONCURRENCY

            },

            (_, i) =>
                worker(
                    i + 1
                )

        )

    );



    // ============================================================
    // FINAL VALIDATION
    // ============================================================

    const productsWithVariants =
        products.filter(
            p =>
                Array.isArray(
                    p.variants
                ) &&
                p.variants.length > 0
        ).length;


    const productsWithoutVariants =
        products.length -
        productsWithVariants;


    const productsWithErrors =
        products.filter(
            p =>
                !!p.variant_error
        ).length;


    const averageVariants =
        totalVariants /
        Math.max(
            products.length,
            1
        );



    // ============================================================
    // PRICE VALIDATION
    // ============================================================

    const productsWithPrice =
        products.filter(
            p =>
                Number(
                    p.price || 0
                ) > 0
        ).length;


    const productsWithoutPrice =
        products.length -
        productsWithPrice;


    const productsWithPdpPrice =
        products.filter(
            p =>
                p.price_source ===
                "pdp"
        ).length;


    const productsWithListingPrice =
        products.filter(
            p =>
                p.price_source ===
                "listing"
        ).length;


    const productsWithNoPrice =
        products.filter(
            p =>
                p.price_source ===
                "unavailable"
        ).length;



    // ============================================================
    // PRICE VALIDATION LOG
    // ============================================================

    console.log("");


    console.log(
        "----------------------------------------------"
    );


    console.log(
        "PRICE VALIDATION"
    );


    console.log(
        "----------------------------------------------"
    );


    console.log(
        `Products With Price    : ${productsWithPrice}`
    );


    console.log(
        `PDP Price              : ${productsWithPdpPrice}`
    );


    console.log(
        `Listing Price          : ${productsWithListingPrice}`
    );


    console.log(
        `No Price               : ${productsWithNoPrice}`
    );


    console.log(
        "----------------------------------------------"
    );


    console.log("");



    // ============================================================
    // SHOW FIRST 10 PRICES
    //
    // This makes it very easy to verify whether the fix worked.
    // ============================================================

    console.log(
        "FIRST 10 PRODUCT PRICES:"
    );


    products
        .slice(
            0,
            10
        )
        .forEach(
            (product, index) => {

                console.log(

                    `${index + 1}. ` +

                    `${product.title}` +

                    ` | Price: ${product.price || 0}` +

                    ` | MRP: ${product.mrp || 0}` +

                    ` | Source: ${product.price_source}`

                );

            }
        );


    console.log("");



    // ============================================================
    // OUTPUT
    // ============================================================

    const output = {

        schema_version:
            1,


        source:
            "tatacliq",


        brand:
            "Columbia",


        platform:
            "Tata Cliq Luxury",


        scrape_date:
            new Date()
                .toISOString()
                .slice(
                    0,
                    10
                ),


        scraped_at:
            new Date()
                .toISOString(),


        expected_products:
            totalResults,


        total_products:
            products.length,


        missing_products:
            Math.max(
                0,
                totalResults -
                products.length
            ),


        total_variants:
            totalVariants,


        products_with_price:
            productsWithPrice,


        products_without_price:
            productsWithoutPrice,


        products_with_pdp_price:
            productsWithPdpPrice,


        products_with_listing_price:
            productsWithListingPrice,


        products_without_any_price:
            productsWithNoPrice,


        average_variants_per_product:
            Number(
                averageVariants.toFixed(
                    2
                )
            ),


        products_with_variants:
            productsWithVariants,


        products_without_variants:
            productsWithoutVariants,


        failed_pdp_products:
            productsWithErrors,


        failed_listing_pages:
            listingFailedPages.map(
                page =>
                    page + 1
            ),


        failed_product_ids:
            failedPdpProducts,


        products

    };

        // ============================================================
    // DOWNLOAD JSON
    // ============================================================

    function downloadJSON(
        data,
        filename
    ) {

        const blob =
            new Blob(
                [
                    JSON.stringify(
                        data,
                        null,
                        2
                    )
                ],
                {
                    type:
                        "application/json"
                }
            );


        const url =
            URL.createObjectURL(
                blob
            );


        const a =
            document.createElement(
                "a"
            );


        a.href =
            url;


        a.download =
            filename;


        document.body.appendChild(
            a
        );


        a.click();


        document.body.removeChild(
            a
        );


        setTimeout(
            () =>
                URL.revokeObjectURL(
                    url
                ),
            1000
        );
    }



    // ============================================================
    // FINAL PROGRESS
    // ============================================================

    updateProgress({

        stage:
            "Completed",


        current:
            products.length,


        total:
            products.length,


        total_variants:
            totalVariants,


        failed_products:
            failedPdpProducts.length

    });



    // ============================================================
    // FINAL REPORT
    // ============================================================

    console.log("");


    console.log("");


    console.log(
        "=============================================="
    );


    console.log(
        "              SCRAPE COMPLETE"
    );


    console.log(
        "=============================================="
    );


    console.log("");


    console.log(
        `Expected Products       : ${totalResults}`
    );


    console.log(
        `Products Collected      : ${products.length}`
    );


    console.log(
        `Missing Products        : ${
            Math.max(
                0,
                totalResults -
                products.length
            )
        }`
    );


    console.log(
        `Total Variants          : ${totalVariants}`
    );


    console.log(
        `Products With Price     : ${productsWithPrice}`
    );


    console.log(
        `Products Without Price  : ${productsWithoutPrice}`
    );


    console.log(
        `PDP Prices              : ${productsWithPdpPrice}`
    );


    console.log(
        `Listing Prices          : ${productsWithListingPrice}`
    );


    console.log(
        `No Price                : ${productsWithNoPrice}`
    );


    console.log(
        `Average Variants/Product: ${averageVariants.toFixed(2)}`
    );


    console.log(
        `Products With Variants  : ${productsWithVariants}`
    );


    console.log(
        `Products Without        : ${productsWithoutVariants}`
    );


    console.log(
        `Failed PDPs             : ${productsWithErrors}`
    );


    console.log(
        `Failed Listing Pages    : ${listingFailedPages.length}`
    );


    console.log("");


    console.log(
        "=============================================="
    );


    console.log("");



    // ============================================================
    // FAILED PDP PRODUCTS
    // ============================================================

    if (
        failedPdpProducts.length
    ) {

        console.warn(
            "Failed PDP product IDs:",
            failedPdpProducts
        );
    }



    // ============================================================
    // FAILED LISTING PAGES
    // ============================================================

    if (
        listingFailedPages.length
    ) {

        console.warn(
            "Failed listing pages:",
            listingFailedPages.map(
                p =>
                    p + 1
            )
        );
    }



    // ============================================================
    // STORE OUTPUT GLOBALLY
    // ============================================================

    window.__TATA_LUX_PRODUCTS__ = output;
    window.__TATA_LUX_SCRAPER_DONE__ = true;
    window.__SCRAPER_DONE__ = true;

    // ============================================================
    // DOWNLOAD
    // ============================================================

    if (typeof window !== "undefined" && !window.__IS_PLAYWRIGHT__) {
        try {
            downloadJSON(output, "tata_lux_columbia_products.json");
            console.log("Downloaded:", "tata_lux_columbia_products.json");
        } catch (_) {}
    }

})();