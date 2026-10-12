import React, { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import {
  ArrowLeft,
  RotateCw,
  ExternalLink,
  ChevronRight,
  Maximize2,
  Check,
  Tag,
  ShieldCheck,
  TrendingDown,
} from "lucide-react";
import productService from "../services/productService";
import { ProductFamily, PlatformListing } from "../types";
import PlatformLogo from "../components/brand/PlatformLogo";

export const ProductDetailsPage: React.FC = () => {
  const { familyId } = useParams<{ familyId: string }>();
  const [product, setProduct] = useState<ProductFamily | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // User selections
  const [selectedImage, setSelectedImage] = useState<string>("");
  const [selectedVariantIndex, setSelectedVariantIndex] = useState<number>(0);
  const [selectedSize, setSelectedSize] = useState<string>("9");
  const [sortOrder, setSortOrder] = useState<string>("price_asc");
  const [showOnlyAvailable, setShowOnlyAvailable] = useState<boolean>(false);
  const [selectedOfferModal, setSelectedOfferModal] = useState<any | null>(null);

  useEffect(() => {
    if (familyId) {
      loadProduct(familyId);
    }
  }, [familyId]);

  const loadProduct = async (id: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await productService.getProductDetails(id);
      setProduct(data);
      setSelectedImage(data.image_url || "");
      if (data.sizes && data.sizes.length > 0) {
        setSelectedSize(data.sizes[0]);
      }
    } catch (err: any) {
      setError(err.message || "Failed to load product details.");
    } finally {
      setIsLoading(false);
    }
  };

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-8 py-20 text-center space-y-3">
        <div className="w-10 h-10 border-3 border-sky-200 border-t-sky-500 rounded-full animate-spin mx-auto" />
        <p className="text-sm font-semibold text-slate-600">Gathering 7-platform intelligence...</p>
      </div>
    );
  }

  if (error || !product) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-8 py-20 text-center space-y-4">
        <div className="bg-rose-50 text-rose-700 p-6 rounded-2xl border border-rose-200 max-w-md mx-auto">
          <p className="font-bold text-base mb-1">Product Not Found</p>
          <p className="text-xs text-rose-600">{error || "Could not retrieve product family details."}</p>
          <Link
            to="/home"
            className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 bg-rose-600 text-white rounded-xl text-xs font-bold"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Return to Search</span>
          </Link>
        </div>
      </div>
    );
  }

  // Thumbnails gallery
  const allImages = Array.from(new Set([product.image_url, ...product.gallery_images].filter(Boolean) as string[]));

  // Size list
  const sizeOptions = product.sizes && product.sizes.length > 0
    ? product.sizes
    : ["6", "7", "8", "9", "10", "11", "12"];

  // Sort and filter platform listings
  let filteredPlatforms = [...product.platforms];
  if (showOnlyAvailable) {
    filteredPlatforms = filteredPlatforms.filter((p) => p.price !== null && p.availability_status !== "Out of stock");
  }

  filteredPlatforms.sort((a, b) => {
    if (sortOrder === "price_asc") {
      const pa = a.price ?? 999999;
      const pb = b.price ?? 999999;
      return pa - pb;
    }
    if (sortOrder === "price_desc") {
      const pa = a.price ?? 0;
      const pb = b.price ?? 0;
      return pb - pa;
    }
    return 0;
  });

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-8 py-6 space-y-8">
      {/* Top Navigation & Status Bar */}
      <div className="flex items-center justify-between gap-4">
        <Link
          to="/home"
          className="inline-flex items-center gap-2 text-xs sm:text-sm font-semibold text-slate-600 hover:text-sky-600 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Back to search</span>
        </Link>

        <div className="flex items-center gap-2 text-xs text-slate-500 font-medium">
          <span>Last updated: {product.data_freshness || "10 Oct 2026, 11:42 AM"}</span>
          <button
            onClick={() => loadProduct(product.family_id)}
            className="p-1 hover:text-sky-600 transition-colors cursor-pointer"
            title="Refresh price snapshot"
          >
            <RotateCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Top 3-Part Desktop Section */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 bg-white p-6 sm:p-8 rounded-3xl border border-slate-200/90 shadow-sm">
        {/* Left Column (lg: 4 cols): Gallery & Main Product Image */}
        <div className="lg:col-span-4 flex gap-4">
          {/* Vertical Thumbnail Strip */}
          <div className="flex flex-col gap-2 shrink-0">
            {allImages.slice(0, 4).map((img, idx) => (
              <button
                key={idx}
                onClick={() => setSelectedImage(img)}
                className={`w-14 h-14 rounded-xl border p-1 bg-slate-50 overflow-hidden transition-all ${
                  selectedImage === img
                    ? "border-sky-500 ring-2 ring-sky-200"
                    : "border-slate-200 hover:border-slate-300 opacity-80 hover:opacity-100"
                }`}
              >
                <img src={img} alt="Thumb" className="w-full h-full object-contain mix-blend-multiply" />
              </button>
            ))}
          </div>

          {/* Large Main Preview */}
          <div className="relative flex-1 bg-slate-50/70 rounded-2xl border border-slate-100 p-6 flex items-center justify-center min-h-[300px]">
            <img
              src={selectedImage || product.image_url || "/vantis_logo.png"}
              alt={product.title}
              className="max-h-[300px] w-full object-contain mix-blend-multiply transition-all hover:scale-105"
            />
            <button
              onClick={() => window.open(selectedImage || product.image_url || "", "_blank")}
              className="absolute bottom-3 right-3 p-2 rounded-xl bg-white/90 border border-slate-200 text-slate-500 hover:text-slate-900 shadow-xs cursor-pointer"
              title="Expand full image"
            >
              <Maximize2 className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Center Column (lg: 5 cols): Title, Identifiers, Color swatches, Sizes */}
        <div className="lg:col-span-5 space-y-4">
          <div className="space-y-1">
            <div className="inline-flex items-center gap-1.5 text-xs font-bold text-sky-600 uppercase tracking-wider">
              <span>{product.brand}</span>
            </div>
            <h1 className="text-xl sm:text-2xl font-black text-slate-900 tracking-tight leading-snug">
              {product.title}
            </h1>
          </div>

          {/* Identifier Row */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500 font-mono py-1 border-y border-slate-100">
            {product.style && (
              <span>
                Style: <span className="font-semibold text-slate-800">{product.style}</span>
              </span>
            )}
            {product.style && product.ean && <span className="text-slate-200">|</span>}
            {product.ean && (
              <span>
                EAN: <span className="font-semibold text-slate-800">{product.ean}</span>
              </span>
            )}
            <span className="text-slate-200">|</span>
            <span>
              Category: <span className="font-semibold text-slate-800">{product.category}</span>
            </span>
            <span className="text-slate-200">|</span>
            <span>
              Gender: <span className="font-semibold text-slate-800">{product.gender}</span>
            </span>
          </div>

          {/* Tags */}
          <div className="flex flex-wrap gap-1.5">
            {product.tags.map((tag, idx) => (
              <span
                key={idx}
                className="bg-sky-50 text-sky-700 text-xs font-semibold px-2.5 py-0.5 rounded-full border border-sky-100"
              >
                {tag}
              </span>
            ))}
          </div>

          {/* Colour / Variant Selector */}
          <div className="space-y-2 pt-2">
            <div className="flex items-center justify-between text-xs font-bold text-slate-700">
              <span>Colour / Variant</span>
              <span className="text-slate-400 font-normal">
                {product.colours_count || 4} variants available
              </span>
            </div>

            <div className="flex items-center gap-2">
              {[0, 1, 2, 3].map((vIdx) => (
                <button
                  key={vIdx}
                  onClick={() => setSelectedVariantIndex(vIdx)}
                  className={`relative w-14 h-14 rounded-xl border p-1 bg-slate-50 overflow-hidden transition-all ${
                    selectedVariantIndex === vIdx
                      ? "border-sky-500 ring-2 ring-sky-200"
                      : "border-slate-200 hover:border-slate-300"
                  }`}
                >
                  <img
                    src={allImages[vIdx % allImages.length] || product.image_url || ""}
                    alt={`Variant ${vIdx}`}
                    className="w-full h-full object-contain mix-blend-multiply"
                  />
                  {selectedVariantIndex === vIdx && (
                    <div className="absolute top-1 right-1 w-3.5 h-3.5 bg-sky-500 rounded-full text-white flex items-center justify-center">
                      <Check className="w-2.5 h-2.5 stroke-[3]" />
                    </div>
                  )}
                </button>
              ))}
              <div className="text-xs text-slate-600 font-semibold pl-2">
                Black / Graphite (010)
              </div>
            </div>
          </div>

          {/* Select Size (UK) */}
          <div className="space-y-2 pt-2">
            <div className="flex items-center justify-between text-xs font-bold text-slate-700">
              <span>Select Size (UK)</span>
              <span className="text-sky-600 hover:underline cursor-pointer font-medium">
                View size guide
              </span>
            </div>

            <div className="flex flex-wrap gap-2">
              {sizeOptions.map((sz) => (
                <button
                  key={sz}
                  onClick={() => setSelectedSize(sz)}
                  className={`w-10 h-10 rounded-xl text-xs font-bold transition-all ${
                    selectedSize === sz
                      ? "bg-[#079FE0] text-white shadow-xs"
                      : "bg-slate-100 hover:bg-slate-200 text-slate-700"
                  }`}
                >
                  {sz}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-slate-400 font-medium">
              {product.sizes_count} sizes available across catalog
            </p>
          </div>
        </div>

        {/* Right Column (lg: 3 cols): Product Summary Card */}
        <div className="lg:col-span-3 bg-slate-50/70 rounded-2xl border border-slate-100 p-6 flex flex-col justify-between space-y-6">
          <div className="space-y-4">
            <h3 className="font-bold text-slate-900 text-sm">Product Summary</h3>

            {/* 4-Stat Grid */}
            <div className="grid grid-cols-2 gap-2.5">
              <div className="p-3 bg-white rounded-xl border border-slate-200/80 text-center">
                <div className="text-xl font-black text-sky-600">{product.variants_count}</div>
                <div className="text-[11px] text-slate-500 font-medium mt-0.5">Variants</div>
              </div>
              <div className="p-3 bg-white rounded-xl border border-slate-200/80 text-center">
                <div className="text-xl font-black text-sky-600">{product.sizes_count}</div>
                <div className="text-[11px] text-slate-500 font-medium mt-0.5">Sizes</div>
              </div>
              <div className="p-3 bg-white rounded-xl border border-slate-200/80 text-center">
                <div className="text-xl font-black text-sky-600">{product.platforms_count}</div>
                <div className="text-[11px] text-slate-500 font-medium mt-0.5">Platforms</div>
              </div>
              <div className="p-3 bg-white rounded-xl border border-slate-200/80 text-center">
                <div className="text-xl font-black text-sky-600">{product.colours_count || 3}</div>
                <div className="text-[11px] text-slate-500 font-medium mt-0.5">Colours</div>
              </div>
            </div>
          </div>

          {/* Pricing Highlight */}
          <div className="space-y-2 pt-4 border-t border-slate-200">
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-black text-slate-900 tracking-tight">
                ₹{product.lowest_price.toLocaleString("en-IN")}
              </span>
              <span className="text-xs font-bold text-emerald-700 bg-emerald-100/80 px-2 py-0.5 rounded">
                Lowest Price
              </span>
            </div>
            <p className="text-xs text-slate-500 font-medium">
              Across all 7 monitored platforms
            </p>
          </div>
        </div>
      </div>

      {/* Platform Comparison Table Section */}
      <div className="bg-white rounded-3xl border border-slate-200/90 shadow-sm overflow-hidden">
        {/* Table Header Bar */}
        <div className="p-6 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-black text-slate-900 tracking-tight">
              Platform Comparison
            </h2>
            <p className="text-xs text-slate-500 font-medium mt-0.5">
              Selected variant: Black / Graphite (010) | Size: UK {selectedSize}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-4">
            {/* Sort Dropdown */}
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500 font-medium">Sort by</span>
              <select
                value={sortOrder}
                onChange={(e) => setSortOrder(e.target.value)}
                className="bg-slate-50 border border-slate-200 rounded-xl px-3 py-1.5 text-xs font-semibold text-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-500/20"
              >
                <option value="price_asc">Price: Low to High</option>
                <option value="price_desc">Price: High to Low</option>
              </select>
            </div>

            {/* Toggle show only available */}
            <label className="flex items-center gap-2 cursor-pointer text-xs font-semibold text-slate-700 select-none">
              <span>Show only available</span>
              <input
                type="checkbox"
                checked={showOnlyAvailable}
                onChange={(e) => setShowOnlyAvailable(e.target.checked)}
                className="w-4 h-4 text-sky-500 rounded focus:ring-sky-500"
              />
            </label>
          </div>
        </div>

        {/* Comparison Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50/70 border-b border-slate-200/80 text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                <th className="py-3 px-4">Platform</th>
                <th className="py-3 px-4">Product Image</th>
                <th className="py-3 px-4">Listing Title</th>
                <th className="py-3 px-4">Price</th>
                <th className="py-3 px-4">Availability</th>
                <th className="py-3 px-4">Sizes Available</th>
                <th className="py-3 px-4">Offers</th>
                <th className="py-3 px-4">Last Updated</th>
                <th className="py-3 px-4 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs text-slate-700">
              {filteredPlatforms.map((listing: PlatformListing) => {
                const hasListing = listing.price !== null && listing.price !== undefined && listing.price > 0;
                const isLowest = listing.price === product.lowest_price;
                const priceDiff = hasListing && listing.price ? listing.price - product.lowest_price : 0;
                const primaryOffer = listing.offers && listing.offers.length > 0 ? listing.offers[0] : null;

                return (
                  <tr
                    key={listing.platform}
                    className="hover:bg-slate-50/60 transition-colors"
                  >
                    {/* Platform */}
                    <td className="py-4 px-4 font-semibold text-slate-900 whitespace-nowrap">
                      <PlatformLogo platform={listing.platform} showLabel size="md" />
                    </td>

                    {/* Image */}
                    <td className="py-4 px-4">
                      <div className="w-12 h-12 rounded-lg bg-slate-50 border border-slate-100 p-0.5 overflow-hidden flex items-center justify-center">
                        <img
                          src={listing.image_url || product.image_url || "/vantis_logo.png"}
                          alt={listing.listing_title}
                          className="w-full h-full object-contain mix-blend-multiply"
                        />
                      </div>
                    </td>

                    {/* Listing Title & Identifiers */}
                    <td className="py-4 px-4 max-w-xs">
                      <div className="font-semibold text-slate-900 text-xs line-clamp-1">
                        {listing.listing_title}
                      </div>
                      <div className="text-[11px] text-slate-400 font-mono mt-0.5">
                        Style: {product.style || "2005101"} {product.ean && `• EAN: ${product.ean}`}
                      </div>
                    </td>

                    {/* Price & Difference */}
                    <td className="py-4 px-4 whitespace-nowrap">
                      {hasListing ? (
                        <div>
                          <div className="font-extrabold text-sm text-slate-900">
                            ₹{listing.price?.toLocaleString("en-IN")}
                          </div>
                          {isLowest ? (
                            <span className="text-[10px] font-bold text-emerald-700 bg-emerald-50 px-1.5 py-0.2 rounded border border-emerald-200">
                              Lowest
                            </span>
                          ) : (
                            <span className="text-[10px] font-bold text-rose-600">
                              +₹{priceDiff.toLocaleString("en-IN")}
                            </span>
                          )}
                        </div>
                      ) : (
                        <span className="text-slate-300 font-semibold">—</span>
                      )}
                    </td>

                    {/* Availability */}
                    <td className="py-4 px-4 whitespace-nowrap">
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`w-2 h-2 rounded-full ${
                            listing.availability_status === "In stock"
                              ? "bg-emerald-500"
                              : listing.availability_status === "Limited stock"
                              ? "bg-amber-500"
                              : "bg-slate-300"
                          }`}
                        />
                        <span className="font-semibold text-slate-800">
                          {listing.availability_status}
                        </span>
                      </div>
                      <div className="text-[11px] text-slate-400 mt-0.5">
                        {listing.stock_text || "Ships in 1-2 days"}
                      </div>
                    </td>

                    {/* Sizes Available */}
                    <td className="py-4 px-4 whitespace-nowrap">
                      <div className="font-semibold text-slate-800">
                        {hasListing ? listing.sizes_summary : "Unavailable"}
                      </div>
                      <div className="text-[11px] text-slate-400 mt-0.5">
                        {hasListing ? "UK 6 - 12" : "—"}
                      </div>
                    </td>

                    {/* Offers */}
                    <td className="py-4 px-4 max-w-[200px]">
                      {primaryOffer ? (
                        <button
                          type="button"
                          onClick={() => setSelectedOfferModal(primaryOffer)}
                          className="text-left group cursor-pointer"
                        >
                          <div className="text-xs font-bold text-sky-700 bg-sky-50 border border-sky-200 px-2 py-0.5 rounded-full inline-flex items-center gap-1 group-hover:bg-sky-100 transition-colors">
                            <Tag className="w-3 h-3 text-sky-500" />
                            <span className="truncate max-w-[140px]">{primaryOffer.title}</span>
                          </div>
                          <div className="text-[10px] text-slate-400 mt-0.5 truncate max-w-[180px]">
                            {primaryOffer.description || primaryOffer.issuer || "Bank & member promotion"}
                          </div>
                        </button>
                      ) : (
                        <span className="text-slate-400 text-xs">No offers</span>
                      )}
                    </td>

                    {/* Last Updated */}
                    <td className="py-4 px-4 whitespace-nowrap text-[11px] text-slate-500">
                      <div>10 Oct 2026</div>
                      <div className="text-slate-400">10:12 AM</div>
                    </td>

                    {/* Action */}
                    <td className="py-4 px-4 text-right whitespace-nowrap">
                      {hasListing ? (
                        <div className="inline-flex items-center gap-1">
                          <a
                            href={listing.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl border border-slate-200 hover:border-sky-400 hover:bg-sky-50 text-sky-600 font-semibold text-xs transition-all shadow-2xs"
                          >
                            <span>View</span>
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                        </div>
                      ) : (
                        <span className="text-slate-300 text-xs italic">N/A</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Offer Details Popover Modal */}
      {selectedOfferModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-xs p-4">
          <div className="bg-white rounded-2xl p-6 max-w-md w-full shadow-2xl border border-slate-200 space-y-4">
            <div className="flex justify-between items-start">
              <div className="flex items-center gap-2 text-sky-600 font-bold text-base">
                <Tag className="w-5 h-5" />
                <span>{selectedOfferModal.title}</span>
              </div>
              <button
                onClick={() => setSelectedOfferModal(null)}
                className="text-slate-400 hover:text-slate-600 p-1 rounded-lg"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              {selectedOfferModal.description || "Special offer applicable at checkout."}
            </p>

            <div className="p-3 bg-slate-50 rounded-xl space-y-1.5 text-xs text-slate-600 border border-slate-100">
              {selectedOfferModal.code && (
                <div>Coupon Code: <span className="font-mono font-bold text-slate-900">{selectedOfferModal.code}</span></div>
              )}
              {selectedOfferModal.issuer && (
                <div>Issuer / Bank: <span className="font-semibold text-slate-800">{selectedOfferModal.issuer}</span></div>
              )}
              {selectedOfferModal.minimum_transaction_amount && (
                <div>Min Transaction: <span className="font-semibold text-slate-800">₹{selectedOfferModal.minimum_transaction_amount}</span></div>
              )}
              {selectedOfferModal.maximum_discount && (
                <div>Max Discount: <span className="font-semibold text-slate-800">₹{selectedOfferModal.maximum_discount}</span></div>
              )}
            </div>

            <div className="flex justify-end pt-2">
              <button
                onClick={() => setSelectedOfferModal(null)}
                className="px-4 py-2 bg-slate-100 hover:bg-slate-200 rounded-xl text-xs font-semibold text-slate-700"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProductDetailsPage;
