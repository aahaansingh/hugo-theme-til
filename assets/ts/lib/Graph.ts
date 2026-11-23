import Page from './Page';
import type { GraphData, PageGraph, Permalink } from './types';
import { DataSet } from 'vis-network/standalone';
import type { Edge, Node } from 'vis-network/standalone';

const NODE_MIN_SIZE = 4;
const NODE_MAX_SIZE = 16;
const NODE_FOCUS_SIZE = 8;

/** Style for auto-generated links so they read as weaker than explicit backlinks. */
const RELATED_EDGE_OPTIONS = {
  dashes: [4, 4],
  color: { color: '#5d7263', opacity: 0.4 }
};

export class PageNotFoundError extends Error {
  constructor(permalink: string) {
    super(`Page '${permalink}' not found in graph data`);
    this.name = 'PageNotFoundError';
  }
}

export default class Graph {
  public readonly pages: Map<Permalink, Page>;
  public readonly graph: Map<Permalink, PageGraph>;

  constructor(private _data: GraphData) {
    this.pages = new Map<Permalink, Page>();
    this.graph = new Map<Permalink, PageGraph>();

    for (const [permalink, pageData] of Object.entries(this._data.pages)) {
      this.pages.set(permalink, new Page(pageData));
    }

    for (const [permalink, pageGraph] of Object.entries(this._data.graph)) {
      this.graph.set(permalink, pageGraph);
    }
  }

  page(permalink: Permalink): Page {
    const page = this.pages.get(permalink);
    if (!page) {
      throw new PageNotFoundError(permalink);
    }

    return page;
  }

  incomingFor(permalink: Permalink): Page[] {
    const pageGraph = this.graph.get(permalink);
    if (!pageGraph) {
      return [];
    }

    return pageGraph.in.map((permalink) => this.page(permalink));
  }

  outgoingFor(permalink: Permalink): Page[] {
    const pageGraph = this.graph.get(permalink);
    if (!pageGraph) {
      return [];
    }

    return pageGraph.out.map((permalink) => this.page(permalink));
  }

  relatedFor(permalink: Permalink): Page[] {
    const pageGraph = this.graph.get(permalink);
    if (!pageGraph?.related) {
      return [];
    }

    return pageGraph.related.map((permalink) => this.page(permalink));
  }

  /**
   * Adds undirected, dashed edges for auto-generated "related" links. Skips pairs that already
   * have an explicit backlink (either direction) and pairs outside `allowed` when given.
   */
  private addRelatedEdges(edges: DataSet<Edge>, pages: Page[]) {
    const seen = new Set<string>();
    const key = (a: string, b: string) => (a < b ? `${a}|${b}` : `${b}|${a}`);
    edges.forEach((e) => seen.add(key(String(e.from), String(e.to))));
    const allowed = new Set(pages.map((p) => p.id));

    pages.forEach((page) => {
      this.relatedFor(page.permalink).forEach((other) => {
        if (!allowed.has(other.id)) return;
        const k = key(page.id, other.id);
        if (seen.has(k)) return;
        seen.add(k);
        edges.add({ from: page.id, to: other.id, ...RELATED_EDGE_OPTIONS });
      });
    });
  }

  dataForPage(permalink: Permalink): {
    nodes: DataSet<Node>;
    edges: DataSet<Edge>;
  } {
    const page = this.page(permalink);
    const nodes = new DataSet<Node>();
    const edges = new DataSet<Edge>();
    const pages = [
      ...new Set([
        page,
        ...this.incomingFor(permalink),
        ...this.outgoingFor(permalink),
        ...this.relatedFor(permalink)
      ])
    ];

    pages.forEach((p) => {
      nodes.add({
        id: p.id,
        label: p.title,
        group: p.section,
        size: permalink === p.permalink ? NODE_FOCUS_SIZE : NODE_MIN_SIZE
      });

      this.incomingFor(p.permalink).forEach((incoming) => {
        if (pages.includes(incoming)) {
          edges.add({ from: incoming.id, to: p.id });
        }
      });
    });

    this.addRelatedEdges(edges, pages);

    return { nodes, edges };
  }

  data(): { nodes: DataSet<Node>; edges: DataSet<Edge> } {
    const nodes = new DataSet<Node>();
    const edges = new DataSet<Edge>();

    for (const page of this.pages.values()) {
      const incoming = this.incomingFor(page.permalink);

      nodes.add({
        id: page.id,
        label: page.title,
        group: page.section
      });

      incoming.forEach((other) => {
        edges.add({ from: other.id, to: page.id });
      });
    }

    // Node size reflects explicit backlinks only; related edges are added afterwards.
    this.scaleNodeSizes(nodes, this.calcInDegree(nodes, edges));
    this.addRelatedEdges(edges, [...this.pages.values()]);

    return { nodes, edges };
  }

  private calcInDegree(
    nodes: DataSet<Partial<Node>>,
    edges: DataSet<Partial<Edge>>
  ): Record<string, number> {
    const count: Record<string, number> = {};

    nodes.forEach((n) => (count[n.id!] = 0));
    edges.forEach((e) => {
      if (count[e.to] !== undefined) {
        count[e.to] += 1;
      }
    });

    return count;
  }

  private scaleNodeSizes(nodes: DataSet<Partial<Node>>, inDegreeCount: Record<string, number>) {
    const values = Object.values(inDegreeCount);
    const minDegree = Math.min(...values);
    const maxDegree = Math.max(...values);

    nodes.forEach((node) => {
      const degree = inDegreeCount[node.id!];
      const size =
        degree !== undefined
          ? ((degree - minDegree) / (maxDegree - minDegree)) * (NODE_MAX_SIZE - NODE_MIN_SIZE) +
            NODE_MIN_SIZE
          : NODE_MIN_SIZE;
      node.size = isNaN(size) ? NODE_MIN_SIZE : size;
    });
  }
}
