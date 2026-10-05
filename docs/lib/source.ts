import { llms, loader } from 'fumadocs-core/source';
import { docsContentRoute, docsImageRoute, docsRoute } from './shared';
import { defineDocs } from 'fumadocs-mdx/macro';
import { metaSchema, pageSchema } from 'fumadocs-core/source/schema';
import { openapi } from './openapi';

const docs = defineDocs({
  dir: 'content/docs',
  docs: {
    schema: pageSchema,
    postprocess: {
      includeProcessedMarkdown: true,
    },
  },
  meta: {
    schema: metaSchema,
  },
});

// See https://fumadocs.dev/docs/headless/source-api for more info
export const source = loader(
  {
    docs: docs.toFumadocsSource(),
    openapi: await openapi.staticSource({ baseDir: 'api', groupBy: 'tag' }),
  },
  {
    baseUrl: docsRoute,
    plugins: [openapi.loaderPlugin()],
  },
);

export const docsLlms = llms(source, {
  renderPage: async (page) => {
    if (page.type === 'openapi') {
      // The page props also contain the full spec. Print only the endpoints of this page.
      const { operations = [] } = page.data.getOpenAPIPageProps();
      const endpoints = operations.map((item) => `${item.method.toUpperCase()} ${item.path}`);

      return `# ${page.data.title} (${page.url})

${[...endpoints, page.data.description].filter(Boolean).join('\n\n')}`;
    }

    return `# ${page.data.title} (${page.url})

${await page.data.getText('processed')}`;
  },
});
