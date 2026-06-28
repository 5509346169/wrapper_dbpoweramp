# Graphviz Liquid tag — wraps source in a <div data-graphviz> that the
# locally bundled @hpcc-js/wasm-graphviz renderer reads.
# NO CDN — vendored bundle is at assets/vendor/graphviz.js.

module Jekyll
  class GraphvizTag < Liquid::Block
    def render(context)
      body = super.to_s.strip
      escaped = body.gsub("</", "<\\/")
      %(<div class="graphviz" data-graphviz>#{escaped}</div>)
    end
  end
end

Liquid::Template.register_tag("graphviz", Jekyll::GraphvizTag)
