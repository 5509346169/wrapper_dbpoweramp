# Generates /search.json at build time from every Markdown page's title,
# section, summary, audience, and body excerpt. Consumed by the command
# palette. Output is intentionally small (no body indexing) so the file
# fits in a few KB even for large sites.

require "json"

module Jekyll
  class SearchIndexGenerator < Generator
    safe true
    priority :low

    def generate(site)
      pages = site.pages.reject { |p| p.path.start_with?("_site/", "site/") }
      pages = pages.reject { |p| p.data["search"] == false }

      nav = site.data["navigation"] || []
      section_for = {}
      nav.each do |section|
        (section["entries"] || []).each do |entry|
          section_for[entry["slug"]] = section["title"]
        end
      end

      index = pages.map do |page|
        slug = page.data["slug"] || page.basename_without_ext
        {
          url: page.url,
          title: page.data["title"] || page.basename_without_ext,
          section: section_for[slug] || page.data["category"],
          summary: page.data["summary"],
          audience: page.data["audience"] || [],
        }
      end

      json = JSON.generate(index)
      index_path = site.in_dest_dir("search.json")
      File.write(index_path, json)
      Jekyll.logger.info "SearchIndex:", "wrote #{index.length} entries -> search.json"
    end
  end
end
