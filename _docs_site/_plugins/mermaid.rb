# Mermaid Liquid tag — wraps source in a <div class="mermaid">
# that the locally bundled mermaid.js reads and renders on DOMContentLoaded.
# NO CDN — vendored bundle is at assets/vendor/mermaid.js.

module Jekyll
  class MermaidTag < Liquid::Block
    def render(context)
      body = super.to_s.strip
      escaped = body.gsub("</", "<\\/")  # escape any literal closing tags
      %(<div class="mermaid">#{escaped}</div>)
    end
  end
end

Liquid::Template.register_tag("mermaid", Jekyll::MermaidTag)
