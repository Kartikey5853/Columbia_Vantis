import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  Search,
  RotateCcw,
  ChevronDown,
  ChevronUp,
  ChevronRight,
  ExternalLink,
  ArrowRight,
  SlidersHorizontal,
} from "lucide-react";
import productService from "../services/productService";
import { ProductFamilySummary, PaginatedProductsResponse, PlatformListing } from "../types";
import PlatformLogo from "../components/brand/PlatformLogo";

export const CataloguePage: React.FC = () => {
  const navigate = useNavigate();

  // Data state
  const [products, setProducts] = useState<ProductFamilySummary[]>([]);
  const [totalRecords, setTotalRecords] = useState<number>(0);
  const [totalPages, setTotalPages] = useState<number>(1);
  const [categories, setCategories] = useState<string[]>(["All"]);
  const [genders, setGenders] = useState<string[]>(["All"]);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  // Filters & Pagination
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(50);
  const [searchTerm, setSearchTerm] = useState<string>("");
  const [category, setCategory] = useState<string>("All");
  const [gender, setGender] = useState<string>("All");
  const [platform, setPlatform] = useState<string>("All");
  const [priceRange, setPriceRange] = useState<string>("All");
  const [selectedRowIds, setSelectedRowIds] = useState<Set<string>>(new Set());
  const [expandedRowId, setExpandedRowId] = useState<string | null>(null);

  useEffect(() => {
    fetchProducts();
  }, [page, pageSize, category, gender, platform, priceRange]);

  const fetchProducts = async (currentSearchTerm?: string) => {
    setIsLoading(true);
    const searchToUse = currentSearchTerm !== undefined ? currentSearchTerm : searchTerm;

    let minPrice: number | undefined;
    let maxPrice: number | undefined;
    if (priceRange === "under_5k") {
      maxPrice = 5000;
    } else if (priceRange === "5k_10k") {
      minPrice = 5000;
      maxPrice = 10000;
    } else if (priceRange === "10k_15k") {
      minPrice = 10000;
      maxPrice = 15000;
    } else if (priceRange === "above_15k") {
      minPrice = 15000;
    }

    try {
      const res: PaginatedProductsResponse = await productService.getProducts({
        page,
        page_size: pageSize,
        search: searchToUse || undefined,
        category: category !== "All" ? category : undefined,
        gender: gender !== "All" ? gender : undefined,
        platform: platform !== "All" ? platform : undefined,
        min_price: minPrice,
        max_price: maxPrice,
      });

      setProducts(res.products);
      setTotalRecords(res.total_records);
      setTotalPages(res.total_pages);
      if (res.categories && res.categories.length > 0) setCategories(res.categories);
      if (res.genders && res.genders.length > 0) setGenders(res.genders);
    } catch {
      // Fallback
    } finally {
      setIsLoading(false);
    }
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchProducts();
  };

  const clearFilters = () => {
    setSearchTerm("");
    setCategory("All");
    setGender("All");
    setPlatform("All");
    setPriceRange("All");
    setPage(1);
    fetchProducts("");
  };

  const toggleSelectAll = () => {
    if (selectedRowIds.size === products.length) {
      setSelectedRowIds(new Set());
    } else {
      setSelectedRowIds(new Set(products.map((p) => p.family_id)));
    }
  };

  const toggleSelectRow = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const next = new Set(selectedRowIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedRowIds(next);
  };

  const toggleExpand = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedRowId(expandedRowId === id ? null : id);
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-8 py-8 space-y-6">
      {/* Title & Stats */}
      <div className="space-y-1">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl sm:text-3xl font-black text-slate-900 tracking-tight">
            Product Catalogue
          </h1>
          <span className="bg-[#EAF6FE] text-[#079FE0] font-extrabold text-xs sm:text-sm px-3 py-1 rounded-full border border-sky-200">
            {totalRecords.toLocaleString("en-IN")} products
          </span>
        </div>
        <p className="text-xs sm:text-sm text-slate-500 font-medium">
          Browse all products from the master catalogue. Click on a row to view platform details or open the full product page.
        </p>
      </div>

      {/* Filter Toolbar */}
      <div className="bg-white p-4 rounded-2xl border border-slate-200/90 shadow-2xs space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-center">
          {/* Search bar */}
          <div className="md:col-span-4 relative">
            <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearchSubmit(e)}
              placeholder="Search by product name, SKU, EAN, or style..."
              className="w-full pl-9 pr-4 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs sm:text-sm focus:outline-none focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500 transition-all font-medium"
            />
          </div>

          {/* Category Dropdown */}
          <div className="md:col-span-2">
            <select
              value={category}
              onChange={(e) => {
                setCategory(e.target.value);
                setPage(1);
              }}
              className="w-full py-2 px-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-500/20 cursor-pointer"
            >
              <option value="All">Category: All</option>
              {categories.filter((c) => c !== "All").map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>

          {/* Gender Dropdown */}
          <div className="md:col-span-2">
            <select
              value={gender}
              onChange={(e) => {
                setGender(e.target.value);
                setPage(1);
              }}
              className="w-full py-2 px-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-500/20 cursor-pointer"
            >
              <option value="All">Gender: All</option>
              {genders.filter((g) => g !== "All").map((g) => (
                <option key={g} value={g}>{g}</option>
              ))}
            </select>
          </div>

          {/* Platform Availability */}
          <div className="md:col-span-2">
            <select
              value={platform}
              onChange={(e) => {
                setPlatform(e.target.value);
                setPage(1);
              }}
              className="w-full py-2 px-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-500/20 cursor-pointer"
            >
              <option value="All">Platform: All</option>
              <option value="amazon">Amazon</option>
              <option value="tata">Tata CLiQ</option>
              <option value="tata_lux">Tata CLiQ Luxury</option>
              <option value="columbia">Columbia India</option>
              <option value="adv">Advaatars</option>
              <option value="myntra">Myntra</option>
              <option value="ajio">AJIO</option>
            </select>
          </div>

          {/* Price Range Dropdown */}
          <div className="md:col-span-1">
            <select
              value={priceRange}
              onChange={(e) => {
                setPriceRange(e.target.value);
                setPage(1);
              }}
              className="w-full py-2 px-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-500/20 cursor-pointer"
            >
              <option value="All">Price: All</option>
              <option value="under_5k">&lt; ₹5,000</option>
              <option value="5k_10k">₹5K - ₹10K</option>
              <option value="10k_15k">₹10K - ₹15K</option>
              <option value="above_15k">&gt; ₹15,000</option>
            </select>
          </div>

          {/* Clear Filters Button */}
          <div className="md:col-span-1 flex justify-end">
            <button
              onClick={clearFilters}
              className="p-2 text-slate-500 hover:text-rose-600 hover:bg-rose-50 rounded-xl transition-colors border border-slate-200 cursor-pointer"
              title="Clear all filters"
            >
              <RotateCcw className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Main Catalogue Table */}
      <div className="bg-white rounded-2xl border border-slate-200/90 shadow-2xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50/80 border-b border-slate-200 text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                <th className="py-3 px-3 w-8">
                  <input
                    type="checkbox"
                    checked={selectedRowIds.size === products.length && products.length > 0}
                    onChange={toggleSelectAll}
                    className="w-4 h-4 text-sky-500 rounded focus:ring-sky-500"
                  />
                </th>
                <th className="py-3 px-2 w-10 text-center">#</th>
                <th className="py-3 px-3 w-16">Image</th>
                <th className="py-3 px-4">Product Name</th>
                <th className="py-3 px-4">Style / SKU</th>
                <th className="py-3 px-4">EAN</th>
                <th className="py-3 px-3">Category</th>
                <th className="py-3 px-3">Gender</th>
                <th className="py-3 px-3 text-center">Variants</th>
                <th className="py-3 px-3 text-center">Sizes</th>
                <th className="py-3 px-3 text-center">Platforms</th>
                <th className="py-3 px-4">Lowest Price</th>
                <th className="py-3 px-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs text-slate-700">
              {isLoading ? (
                <tr>
                  <td colSpan={13} className="py-20 text-center">
                    <div className="w-8 h-8 border-3 border-sky-200 border-t-sky-500 rounded-full animate-spin mx-auto mb-2" />
                    <span className="text-slate-400 font-semibold">Loading catalogue records...</span>
                  </td>
                </tr>
              ) : products.length === 0 ? (
                <tr>
                  <td colSpan={13} className="py-12 text-center text-slate-400">
                    No products matching current filter criteria.
                  </td>
                </tr>
              ) : (
                products.map((product, idx) => {
                  const isSelected = selectedRowIds.has(product.family_id);
                  const isExpanded = expandedRowId === product.family_id;
                  const rowNumber = (page - 1) * pageSize + idx + 1;

                  return (
                    <React.Fragment key={product.family_id}>
                      <tr
                        onClick={() => setExpandedRowId(isExpanded ? null : product.family_id)}
                        className={`hover:bg-slate-50/70 transition-colors cursor-pointer ${
                          isExpanded ? "bg-sky-50/30" : isSelected ? "bg-sky-50/20" : ""
                        }`}
                      >
                        {/* Checkbox */}
                        <td className="py-3.5 px-3">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onClick={(e) => toggleSelectRow(product.family_id, e)}
                            onChange={() => {}}
                            className="w-4 h-4 text-sky-500 rounded focus:ring-sky-500 cursor-pointer"
                          />
                        </td>

                        {/* Row # */}
                        <td className="py-3.5 px-2 text-center text-slate-400 font-mono text-[11px]">
                          {rowNumber}
                        </td>

                        {/* Image */}
                        <td className="py-3.5 px-3">
                          <div className="w-12 h-12 rounded-lg bg-slate-50 border border-slate-100 p-0.5 overflow-hidden flex items-center justify-center">
                            <img
                              src={product.image_url || "/vantis_logo.png"}
                              alt={product.title}
                              className="w-full h-full object-contain mix-blend-multiply"
                            />
                          </div>
                        </td>

                        {/* Product Name */}
                        <td className="py-3.5 px-4 font-bold text-slate-900 max-w-xs">
                          <div className="line-clamp-1">{product.title}</div>
                        </td>

                        {/* Style / SKU */}
                        <td className="py-3.5 px-4 font-mono font-medium text-slate-700 whitespace-nowrap">
                          {product.style || product.sku || "—"}
                        </td>

                        {/* EAN */}
                        <td className="py-3.5 px-4 font-mono text-slate-500 whitespace-nowrap">
                          {product.ean || "—"}
                        </td>

                        {/* Category */}
                        <td className="py-3.5 px-3 font-semibold text-slate-700 whitespace-nowrap">
                          {product.category}
                        </td>

                        {/* Gender */}
                        <td className="py-3.5 px-3 font-semibold text-slate-600 whitespace-nowrap">
                          {product.gender}
                        </td>

                        {/* Variants */}
                        <td className="py-3.5 px-3 text-center font-bold text-slate-800">
                          {product.variants_count}
                        </td>

                        {/* Sizes */}
                        <td className="py-3.5 px-3 text-center font-bold text-slate-800">
                          {product.sizes_count}
                        </td>

                        {/* Platforms */}
                        <td className="py-3.5 px-3 text-center font-bold text-sky-600">
                          {product.platforms_count}
                        </td>

                        {/* Lowest Price */}
                        <td className="py-3.5 px-4 whitespace-nowrap">
                          <div className="font-extrabold text-slate-900">
                            ₹{product.lowest_price.toLocaleString("en-IN")}
                          </div>
                          {product.discount_percent && product.discount_percent > 0 ? (
                            <span className="text-[10px] font-bold text-emerald-700">
                              ↓ {product.discount_percent}%
                            </span>
                          ) : null}
                        </td>

                        {/* Action Expand */}
                        <td className="py-3.5 px-3 text-right">
                          <button
                            onClick={(e) => toggleExpand(product.family_id, e)}
                            className="p-1 text-slate-400 hover:text-sky-600 transition-colors"
                          >
                            {isExpanded ? (
                              <ChevronUp className="w-4 h-4" />
                            ) : (
                              <ChevronRight className="w-4 h-4" />
                            )}
                          </button>
                        </td>
                      </tr>

                      {/* Expandable Row with 7 Platform Cards (Matching Image 4) */}
                      {isExpanded && (
                        <tr className="bg-sky-50/20">
                          <td colSpan={13} className="p-4 sm:p-6 border-y border-sky-100">
                            <div className="bg-white rounded-2xl p-6 border border-slate-200/90 shadow-sm space-y-6">
                              {/* Top Product Detail Inside Row */}
                              <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
                                <div className="flex items-center gap-5">
                                  <div className="w-24 h-24 rounded-xl bg-slate-50 border border-slate-100 p-1 shrink-0 overflow-hidden">
                                    <img
                                      src={product.image_url || "/vantis_logo.png"}
                                      alt={product.title}
                                      className="w-full h-full object-contain mix-blend-multiply"
                                    />
                                  </div>
                                  <div className="space-y-1.5">
                                    <h4 className="font-extrabold text-base text-slate-900">
                                      {product.title}
                                    </h4>
                                    <div className="text-xs text-slate-500 font-mono">
                                      Style: <span className="font-bold text-slate-800">{product.style || "1780161"}</span>
                                      {product.ean && ` • EAN: ${product.ean}`}
                                    </div>
                                    <div className="flex flex-wrap gap-1.5 pt-1">
                                      {product.tags.map((t, tidx) => (
                                        <span
                                          key={tidx}
                                          className="bg-sky-50 text-sky-700 text-[11px] font-semibold px-2 py-0.5 rounded-full"
                                        >
                                          {t}
                                        </span>
                                      ))}
                                    </div>
                                  </div>
                                </div>

                                {/* Circular Stat Chips & View Details CTA */}
                                <div className="flex items-center gap-4">
                                  <div className="flex items-center gap-2">
                                    <div className="w-14 h-14 rounded-full bg-[#EAF6FE] flex flex-col items-center justify-center text-center">
                                      <span className="text-base font-extrabold text-[#079FE0] leading-none">
                                        {product.variants_count}
                                      </span>
                                      <span className="text-[10px] text-slate-500 font-medium leading-none mt-0.5">
                                        Variants
                                      </span>
                                    </div>
                                    <div className="w-14 h-14 rounded-full bg-[#EAF6FE] flex flex-col items-center justify-center text-center">
                                      <span className="text-base font-extrabold text-[#079FE0] leading-none">
                                        {product.sizes_count}
                                      </span>
                                      <span className="text-[10px] text-slate-500 font-medium leading-none mt-0.5">
                                        Sizes
                                      </span>
                                    </div>
                                    <div className="w-14 h-14 rounded-full bg-[#EAF6FE] flex flex-col items-center justify-center text-center">
                                      <span className="text-base font-extrabold text-[#079FE0] leading-none">
                                        {product.platforms_count}
                                      </span>
                                      <span className="text-[10px] text-slate-500 font-medium leading-none mt-0.5">
                                        Platforms
                                      </span>
                                    </div>
                                  </div>

                                  <div className="text-right pl-4 border-l border-slate-100">
                                    <div className="text-xl font-black text-slate-900">
                                      ₹{product.lowest_price.toLocaleString("en-IN")}
                                    </div>
                                    <div className="text-[11px] font-bold text-slate-400">
                                      Lowest Price {product.discount_percent && `↓ ${product.discount_percent}%`}
                                    </div>
                                    <button
                                      onClick={() => navigate(`/products/${encodeURIComponent(product.family_id)}`)}
                                      className="mt-2 inline-flex items-center gap-1.5 px-4 py-2 bg-[#079FE0] hover:bg-[#068ec8] text-white text-xs font-bold rounded-xl transition-all shadow-xs cursor-pointer"
                                    >
                                      <span>View Details</span>
                                      <ArrowRight className="w-3.5 h-3.5" />
                                    </button>
                                  </div>
                                </div>
                              </div>

                              {/* Platform Availability Grid (Cards for 7 Platforms) */}
                              <div className="space-y-2 pt-2 border-t border-slate-100">
                                <div className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                                  Platform Availability (Selected Variant)
                                </div>
                                <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-7 gap-3">
                                  {product.platforms.map((plat) => {
                                    const hasPlat = plat.price !== null && plat.price !== undefined && plat.price > 0;
                                    return (
                                      <div
                                        key={plat.platform}
                                        className="p-3 bg-slate-50/70 rounded-xl border border-slate-200/80 space-y-1.5"
                                      >
                                        <PlatformLogo platform={plat.platform} showLabel size="sm" />
                                        <div className="font-extrabold text-sm text-slate-900">
                                          {hasPlat ? `₹${plat.price?.toLocaleString("en-IN")}` : "—"}
                                        </div>
                                        <div className="flex items-center gap-1 text-[10px] font-semibold">
                                          <span
                                            className={`w-1.5 h-1.5 rounded-full ${
                                              plat.availability_status === "In stock"
                                                ? "bg-emerald-500"
                                                : plat.availability_status === "Limited stock"
                                                ? "bg-amber-500"
                                                : "bg-slate-300"
                                            }`}
                                          />
                                          <span className="text-slate-600">{plat.availability_status}</span>
                                        </div>
                                        <div className="text-[10px] text-slate-400">
                                          {hasPlat ? plat.sizes_summary : "0 sizes"}
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Footer */}
        <div className="p-4 bg-slate-50/70 border-t border-slate-200 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs font-semibold text-slate-600">
          {/* Page size selector */}
          <div className="flex items-center gap-2">
            <span>Show</span>
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              className="py-1 px-2.5 bg-white border border-slate-200 rounded-lg text-xs font-bold text-slate-800 cursor-pointer"
            >
              <option value={20}>20</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
            <span>products per page</span>
          </div>

          {/* Page Numbers */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={page <= 1}
              className="px-2.5 py-1 rounded-lg border border-slate-200 bg-white hover:bg-slate-100 disabled:opacity-40 transition-colors"
            >
              &lt;
            </button>

            {[1, 2, 3, 4, 5].map((pNum) => {
              if (pNum > totalPages) return null;
              return (
                <button
                  key={pNum}
                  onClick={() => setPage(pNum)}
                  className={`w-7 h-7 rounded-lg transition-colors font-bold ${
                    page === pNum
                      ? "bg-[#079FE0] text-white shadow-2xs"
                      : "bg-white border border-slate-200 hover:bg-slate-100 text-slate-700"
                  }`}
                >
                  {pNum}
                </button>
              );
            })}

            {totalPages > 5 && <span className="px-1 text-slate-400">...</span>}

            {totalPages > 5 && (
              <button
                onClick={() => setPage(totalPages)}
                className={`px-2.5 py-1 rounded-lg border border-slate-200 font-bold ${
                  page === totalPages
                    ? "bg-[#079FE0] text-white"
                    : "bg-white hover:bg-slate-100 text-slate-700"
                }`}
              >
                {totalPages}
              </button>
            )}

            <button
              onClick={() => setPage(Math.min(totalPages, page + 1))}
              disabled={page >= totalPages}
              className="px-2.5 py-1 rounded-lg border border-slate-200 bg-white hover:bg-slate-100 disabled:opacity-40 transition-colors"
            >
              &gt;
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CataloguePage;
